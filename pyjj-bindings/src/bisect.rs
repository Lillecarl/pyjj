//! `jj bisect`'s search, as a Python object.
//!
//! `jj_lib::bisect::Bisector<'repo>` borrows the repo it searches. A
//! `#[pyclass]` cannot hold that borrow: a Python object outlives every
//! Rust scope, so there is no lifetime to give it. Wrapping the borrow in
//! a self-referential struct needs `unsafe`, and this crate has no
//! precedent for that.
//!
//! So this type does not store a `Bisector` at all. It stores the search
//! state, which is small and fully owned: the input range plus the three
//! sets of marks. Every call rebuilds a real `Bisector` from that state,
//! uses it, and drops it before returning. The borrow never escapes the
//! call, and everything the pyclass holds is `Send + Sync`.
//!
//! Replaying the marks into a fresh `Bisector` is safe, in this order:
//! bad, then good, then skipped. `Bisector::new` seeds `bad` with the
//! range's heads, so the replayed `bad` set is always a superset of what
//! the constructor seeded, and re-inserting an id it already holds is a
//! `HashSet` no-op. `mark_bad` only asserts against `good`/`skipped`,
//! both still empty at that point. `mark_good` and `mark_skipped` assert
//! against `bad`, and the sets this type stores are pairwise disjoint,
//! because `mark()` below rejects a conflicting id before recording it.
//!
//! That rejection matters on its own: jj_lib's `assert!`s stay live in
//! release builds, and a tripped one reaches Python as a
//! `PanicException`. Validating first turns those into `ValueError`.

use std::collections::HashSet;
use std::sync::Arc;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use jj_lib::backend::CommitId;
use jj_lib::bisect::{BisectionResult, Bisector, Evaluation, NextStep};
use jj_lib::object_id::ObjectId as _;
use jj_lib::revset::ResolvedRevsetExpression;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{map_py_err, map_revset_eval_err};
use crate::ids::PyCommitId;
use crate::settings::PyUserSettings;

/// One step of a bisection, from `Bisector.next_step()`.
///
/// `kind` is `"evaluate"` -- `commit` holds the revision to test -- or
/// `"done"`, where `result` is `"found"` (`commits` holds the first bad
/// revision, or several when the input range had disjoint heads),
/// `"indeterminate"` (the answer sits inside a skipped range, or the
/// range was empty), or `"abort"`.
#[pyclass(name = "BisectStep", frozen, get_all)]
pub struct PyBisectStep {
    kind: String,
    commit: Option<PyCommit>,
    result: Option<String>,
    commits: Vec<PyCommit>,
}

/// The exit-status protocol `jj bisect run` uses, as a name.
fn evaluation_from_str(name: &str) -> PyResult<Evaluation> {
    match name {
        "good" => Ok(Evaluation::Good),
        "bad" => Ok(Evaluation::Bad),
        "skip" => Ok(Evaluation::Skip),
        "abort" => Ok(Evaluation::Abort),
        other => Err(PyValueError::new_err(format!(
            "unknown evaluation {other:?} (expected \"good\", \"bad\", \"skip\" or \"abort\")"
        ))),
    }
}

/// `jj bisect`'s binary search over a range of commits.
///
/// The range's heads are assumed bad and are marked so at construction.
/// Parents of the range's roots are assumed good. Call `next_step()`,
/// test the commit it hands back, report the outcome with `mark()`, and
/// repeat until `next_step()` reports `"done"`.
#[pyclass(name = "Bisector")]
pub struct PyBisector {
    repo: Arc<jj_lib::repo::ReadonlyRepo>,
    input_range: Arc<ResolvedRevsetExpression>,
    good: HashSet<CommitId>,
    bad: HashSet<CommitId>,
    skipped: HashSet<CommitId>,
    aborted: bool,
}

impl PyBisector {
    /// Rebuild a real `Bisector` holding this object's state. See the
    /// module docs for why the replay order is bad, good, skipped.
    fn rebuild(&self) -> PyResult<Bisector<'_>> {
        let mut bisector =
            pollster::block_on(Bisector::new(self.repo.as_ref(), self.input_range.clone()))
                .map_err(map_py_err)?;
        for id in &self.bad {
            bisector.mark_bad(id.clone());
        }
        for id in &self.good {
            bisector.mark_good(id.clone());
        }
        for id in &self.skipped {
            bisector.mark_skipped(id.clone());
        }
        Ok(bisector)
    }

    fn wrap_commit(&self, commit: jj_lib::commit::Commit) -> PyCommit {
        PyCommit {
            inner: commit,
            _repo: Some(self.repo.clone()),
        }
    }
}

#[pymethods]
impl PyBisector {
    /// Start a bisection over `revisions`, a revset naming the range --
    /// typically something like `"v1.0..main"`. Several expressions are
    /// unioned, matching `jj bisect run`'s repeatable `--range`.
    #[new]
    #[pyo3(signature = (repo, settings, revisions))]
    fn new(repo: &PyReadonlyRepo, settings: &PyUserSettings, revisions: Vec<String>) -> PyResult<Self> {
        if revisions.is_empty() {
            return Err(PyValueError::new_err("bisect needs at least one range"));
        }
        // One union expression, so evaluation order matches `jj`'s own
        // `parse_union_revsets` rather than a per-item concatenation.
        let union = revisions
            .iter()
            .map(|expr| format!("({expr})"))
            .collect::<Vec<_>>()
            .join(" | ");
        let input_range = crate::revset::resolve_revset(
            repo.inner.as_ref(),
            &repo.workspace_root,
            &repo.workspace_name,
            settings,
            &union,
        )?;
        // Let jj_lib seed the bad set from the range's heads rather than
        // reimplementing that rule here.
        let seeded = pollster::block_on(Bisector::new(repo.inner.as_ref(), input_range.clone()))
            .map_err(map_py_err)?;
        let bad = seeded.bad_commits().clone();
        Ok(Self {
            repo: repo.inner.clone(),
            input_range,
            good: HashSet::new(),
            bad,
            skipped: HashSet::new(),
            aborted: false,
        })
    }

    /// The next commit to evaluate, or the finished result. See
    /// `BisectStep`.
    fn next_step(&mut self) -> PyResult<PyBisectStep> {
        if self.aborted {
            return Ok(PyBisectStep {
                kind: "done".to_string(),
                commit: None,
                result: Some("abort".to_string()),
                commits: Vec::new(),
            });
        }
        let mut bisector = self.rebuild()?;
        let step = pollster::block_on(bisector.next_step()).map_err(map_py_err)?;
        Ok(match step {
            NextStep::Evaluate(commit) => PyBisectStep {
                kind: "evaluate".to_string(),
                commit: Some(self.wrap_commit(commit)),
                result: None,
                commits: Vec::new(),
            },
            NextStep::Done(BisectionResult::Found(commits)) => PyBisectStep {
                kind: "done".to_string(),
                commit: None,
                result: Some("found".to_string()),
                commits: commits
                    .into_iter()
                    .map(|commit| self.wrap_commit(commit))
                    .collect(),
            },
            NextStep::Done(BisectionResult::Indeterminate) => PyBisectStep {
                kind: "done".to_string(),
                commit: None,
                result: Some("indeterminate".to_string()),
                commits: Vec::new(),
            },
            NextStep::Done(BisectionResult::Abort) => PyBisectStep {
                kind: "done".to_string(),
                commit: None,
                result: Some("abort".to_string()),
                commits: Vec::new(),
            },
        })
    }

    /// Record the outcome of testing `id`. `evaluation` is `"good"`,
    /// `"bad"`, `"skip"` or `"abort"`.
    ///
    /// Raises `ValueError` when the id already carries a different mark,
    /// or once the bisection has aborted.
    fn mark(&mut self, id: &PyCommitId, evaluation: &str) -> PyResult<()> {
        let evaluation = evaluation_from_str(evaluation)?;
        if self.aborted {
            return Err(PyValueError::new_err("bisection has been aborted"));
        }
        let commit_id = id.0.clone();
        let conflict = |set: &HashSet<CommitId>, name: &str| {
            set.contains(&commit_id)
                .then(|| format!("commit {} is already marked {name}", commit_id.hex()))
        };
        let clash = match evaluation {
            Evaluation::Good => conflict(&self.bad, "bad").or_else(|| conflict(&self.skipped, "skipped")),
            Evaluation::Bad => conflict(&self.good, "good").or_else(|| conflict(&self.skipped, "skipped")),
            Evaluation::Skip => conflict(&self.good, "good").or_else(|| conflict(&self.bad, "bad")),
            Evaluation::Abort => conflict(&self.good, "good")
                .or_else(|| conflict(&self.bad, "bad"))
                .or_else(|| conflict(&self.skipped, "skipped")),
        };
        if let Some(message) = clash {
            return Err(PyValueError::new_err(message));
        }
        match evaluation {
            Evaluation::Good => {
                self.good.insert(commit_id);
            }
            Evaluation::Bad => {
                self.bad.insert(commit_id);
            }
            Evaluation::Skip => {
                self.skipped.insert(commit_id);
            }
            Evaluation::Abort => {
                self.aborted = true;
            }
        }
        Ok(())
    }

    /// `"good"` and `"bad"` swapped, `"skip"` and `"abort"` unchanged --
    /// what `jj bisect run --find-good` does to each outcome.
    #[staticmethod]
    fn invert(evaluation: &str) -> PyResult<String> {
        Ok(match evaluation_from_str(evaluation)?.invert() {
            Evaluation::Good => "good",
            Evaluation::Bad => "bad",
            Evaluation::Skip => "skip",
            Evaluation::Abort => "abort",
        }
        .to_string())
    }

    /// How many commits remain to test, as `(lower, upper)`. `upper` is
    /// `None` when the count is not bounded yet. This is what `jj bisect
    /// run` turns into its "N revisions left to test" line.
    fn remaining_count(&self) -> PyResult<(usize, Option<usize>)> {
        let bisector = self.rebuild()?;
        let revset = pollster::block_on(bisector.remaining_revset()).map_err(map_py_err)?;
        revset.count_estimate().map_err(map_revset_eval_err)
    }

    #[getter]
    fn good_commits(&self) -> Vec<PyCommitId> {
        self.good.iter().cloned().map(PyCommitId).collect()
    }

    #[getter]
    fn bad_commits(&self) -> Vec<PyCommitId> {
        self.bad.iter().cloned().map(PyCommitId).collect()
    }

    #[getter]
    fn skipped_commits(&self) -> Vec<PyCommitId> {
        self.skipped.iter().cloned().map(PyCommitId).collect()
    }

    #[getter]
    fn aborted(&self) -> bool {
        self.aborted
    }
}
