use pyo3::prelude::*;

use jj_lib::op_store::RefTarget;
use jj_lib::ref_name::RefName;

use crate::ids::PyCommitId;

/// A local tag: a name pointing at one or more commits.
///
/// Structurally identical to `Bookmark` (both are backed by the same
/// `jj_lib::op_store::RefTarget`/`RefName` machinery), kept as a distinct
/// type since jj treats tags and bookmarks as different concepts -- tags
/// are typically populated by `jj git import` from real Git tags rather
/// than moved by hand, though nothing here prevents setting them directly.
/// More than one target id means the tag is conflicted (e.g. moved
/// differently by concurrent operations) — check `has_conflict`.
#[pyclass(name = "Tag", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyTag {
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub target_ids: Vec<PyCommitId>,
    /// The commits a conflicted tag moved *away* from. Empty unless
    /// `has_conflict`. jj lists these as the `-` side, against
    /// `target_ids` as the `+` side, with the same template it uses for
    /// a bookmark.
    #[pyo3(get)]
    pub removed_ids: Vec<PyCommitId>,
    #[pyo3(get)]
    pub has_conflict: bool,
}

impl PyTag {
    pub(crate) fn from_target(name: &RefName, target: &RefTarget) -> Self {
        Self {
            name: name.as_str().to_string(),
            target_ids: target.added_ids().map(PyCommitId::from).collect(),
            removed_ids: target.removed_ids().map(PyCommitId::from).collect(),
            has_conflict: target.has_conflict(),
        }
    }
}

#[pymethods]
impl PyTag {
    fn __repr__(&self) -> String {
        let conflict = if self.has_conflict { "True" } else { "False" };
        format!("Tag({}, conflict={conflict})", self.name)
    }

    fn __eq__(&self, other: &Self) -> bool {
        self.name == other.name
            && self.has_conflict == other.has_conflict
            && self.target_ids == other.target_ids
    }
}


/// A remote tag: a name on a remote, pointing at commits.
///
/// jj spells these `name@remote`, the same as a remote bookmark. A
/// colocated repository has a `git` remote, so every tag the repository
/// exported has one of these beside it -- which is what `jj tag list
/// --all-remotes` prints and a plain listing leaves out.
#[pyclass(name = "RemoteTag", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyRemoteTag {
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub remote: String,
    #[pyo3(get)]
    pub target_ids: Vec<PyCommitId>,
    /// The commits a conflicted remote tag moved *away* from, against
    /// `target_ids` as the side it moved to. Empty unless `has_conflict`.
    #[pyo3(get)]
    pub removed_ids: Vec<PyCommitId>,
    #[pyo3(get)]
    pub has_conflict: bool,
    /// Whether the local tag of the same name follows this one.
    #[pyo3(get)]
    pub tracked: bool,
}

#[pymethods]
impl PyRemoteTag {
    /// `name@remote`, the way jj writes it.
    #[getter]
    fn symbol(&self) -> String {
        format!("{}@{}", self.name, self.remote)
    }

    fn __repr__(&self) -> String {
        format!("RemoteTag({})", self.symbol())
    }
}
