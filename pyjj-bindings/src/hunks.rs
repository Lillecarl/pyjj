use std::collections::HashSet;

use pyo3::prelude::*;

use jj_lib::diff::{ContentDiff, DiffHunkKind};
use jj_lib::diff_presentation::LineCompareMode;

/// How `jj diff` compares two lines: literally, or with `-w` / `-b`,
/// which let it call two lines the same across whitespace.
fn compare_mode(name: &str) -> PyResult<LineCompareMode> {
    match name {
        "exact" => Ok(LineCompareMode::Exact),
        "ignore-all-space" => Ok(LineCompareMode::IgnoreAllSpace),
        "ignore-space-change" => Ok(LineCompareMode::IgnoreSpaceChange),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "unknown compare mode {name:?}"
        ))),
    }
}

/// One line-level diff hunk between two versions of a file's content. Only
/// "different" segments are returned (unchanged text is omitted); `index`
/// is 0-based, in file order, and is what `Transaction.squash()`/
/// `.split_selected()`'s `hunks={path: [indices]}` parameter expects.
#[pyclass(name = "Hunk", frozen)]
pub struct PyHunk {
    #[pyo3(get)]
    pub index: usize,
    #[pyo3(get)]
    pub before: Vec<u8>,
    #[pyo3(get)]
    pub after: Vec<u8>,
}

#[pymethods]
impl PyHunk {
    fn __repr__(&self) -> String {
        format!(
            "Hunk(index={}, before={} bytes, after={} bytes)",
            self.index,
            self.before.len(),
            self.after.len()
        )
    }
}

/// Computes line-level diff hunks between `before` and `after` file
/// content. Pure content diff -- no repo/commit access needed, so it can
/// be used to preview a selection before committing to it.
#[pyfunction]
pub fn diff_hunks(before: &[u8], after: &[u8]) -> Vec<PyHunk> {
    diff_hunks_raw(before, after)
        .into_iter()
        .map(|(index, before, after)| PyHunk {
            index,
            before: before.to_vec(),
            after: after.to_vec(),
        })
        .collect()
}

pub(crate) fn diff_hunks_raw<'a>(
    before: &'a [u8],
    after: &'a [u8],
) -> Vec<(usize, &'a [u8], &'a [u8])> {
    let diff = ContentDiff::by_line([before, after]);
    let mut index = 0;
    let mut result = Vec::new();
    for hunk in diff.hunks() {
        if hunk.kind == DiffHunkKind::Different {
            result.push((index, hunk.contents[0].as_ref(), hunk.contents[1].as_ref()));
            index += 1;
        }
    }
    result
}

/// Reconstructs file content by taking the hunks in `selected` (indices
/// from `diff_hunks(before, after)`) from `after`, and leaving every other
/// hunk as it was in `before`. Unchanged (matching) regions pass through
/// unmodified either way.
pub(crate) fn apply_hunk_selection(
    before: &[u8],
    after: &[u8],
    selected: &HashSet<usize>,
) -> Vec<u8> {
    let diff = ContentDiff::by_line([before, after]);
    let mut index = 0;
    let mut result = Vec::new();
    for hunk in diff.hunks() {
        match hunk.kind {
            DiffHunkKind::Matching => {
                result.extend_from_slice(hunk.contents[0].as_ref());
            }
            DiffHunkKind::Different => {
                let content = if selected.contains(&index) {
                    hunk.contents[1].as_ref()
                } else {
                    hunk.contents[0].as_ref()
                };
                result.extend_from_slice(content);
                index += 1;
            }
        }
    }
    result
}

/// One hunk of a unified (Git-style) diff: the `@@` header numbers plus
/// the lines under it.
///
/// `left_start`/`right_start` are already the numbers a `@@` header
/// prints, so they are 1-based, except that an empty range prints the
/// line before it (0 at the start of a file). `left_len`/`right_len` are
/// line counts, and jj prints both unconditionally -- unlike `git diff`,
/// which omits a count of 1.
#[pyclass(name = "UnifiedHunk", frozen)]
pub struct PyUnifiedHunk {
    #[pyo3(get)]
    pub left_start: usize,
    #[pyo3(get)]
    pub left_len: usize,
    #[pyo3(get)]
    pub right_start: usize,
    #[pyo3(get)]
    pub right_len: usize,
    /// `(kind, tokens)` per line, where kind is `"context"`, `"removed"`
    /// or `"added"`.
    ///
    /// `tokens` splits the line where jj's word diff found a change:
    /// each is `(kind, content)` with kind `"matching"` or `"different"`,
    /// and `jj diff --git` underlines the different ones. Joining the
    /// contents gives the whole line, which keeps its trailing newline
    /// and lacks one exactly when the file does.
    #[pyo3(get)]
    pub lines: Vec<(String, Vec<(String, Vec<u8>)>)>,
}

#[pymethods]
impl PyUnifiedHunk {
    fn __repr__(&self) -> String {
        format!(
            "UnifiedHunk(@@ -{},{} +{},{} @@, {} lines)",
            self.left_start,
            self.left_len,
            self.right_start,
            self.right_len,
            self.lines.len()
        )
    }
}

/// Computes the hunks of a unified diff between `before` and `after`,
/// with `context` unchanged lines around each change.
///
/// This is `jj_lib`'s own `unified_diff_hunks`, which is what `jj diff
/// --git` prints. Line splitting, hunk boundaries and the merging of
/// nearby changes therefore match jj exactly -- a diff built with a
/// different algorithm would not, however the output was formatted.
///
/// `compare` is how two lines are compared: `"exact"`,
/// `"ignore-all-space"` or `"ignore-space-change"`.
#[pyfunction]
#[pyo3(signature = (before, after, context=3, compare="exact"))]
pub fn unified_hunks(
    before: &[u8],
    after: &[u8],
    context: usize,
    compare: &str,
) -> PyResult<Vec<PyUnifiedHunk>> {
    use bstr::BStr;
    use jj_lib::diff_presentation::unified::{DiffLineType, unified_diff_hunks};
    use jj_lib::diff_presentation::DiffTokenType;
    use jj_lib::merge::Diff;

    // "If the chunk size is 0, the first number is one lower than one
    // would expect" -- the POSIX rule jj follows in `diff_util.rs`.
    fn to_line_number(range: &std::ops::Range<usize>) -> usize {
        if range.is_empty() {
            range.start
        } else {
            range.start + 1
        }
    }

    let contents = Diff::new(before, after).map(BStr::new);
    Ok(unified_diff_hunks(contents, context, compare_mode(compare)?)
        .into_iter()
        .map(|hunk| PyUnifiedHunk {
            left_start: to_line_number(&hunk.left_line_range),
            left_len: hunk.left_line_range.len(),
            right_start: to_line_number(&hunk.right_line_range),
            right_len: hunk.right_line_range.len(),
            lines: hunk
                .lines
                .into_iter()
                .map(|(line_type, tokens)| {
                    let kind = match line_type {
                        DiffLineType::Context => "context",
                        DiffLineType::Removed => "removed",
                        DiffLineType::Added => "added",
                    };
                    let tokens = tokens
                        .into_iter()
                        .map(|(token_type, content)| {
                            let token_kind = match token_type {
                                DiffTokenType::Matching => "matching",
                                DiffTokenType::Different => "different",
                            };
                            (token_kind.to_owned(), content.to_vec())
                        })
                        .collect();
                    (kind.to_owned(), tokens)
                })
                .collect(),
        })
        .collect())
}

/// The raw hunks of a content diff: `(kind, before, after)`, where kind
/// is `"matching"` or `"different"`. A matching hunk carries the same
/// content on both sides.
///
/// `by` picks the tokenizer. `"line"` is how jj splits a file first;
/// `"word"` is how it splits a changed region again, to mark only the
/// words that moved. `jj diff`'s default format runs both, so a caller
/// that formats it needs both.
///
/// `compare` is how two lines are compared, and only the line
/// tokenizer reads it: jj's `-w` and `-b` decide which lines changed,
/// never which words did.
#[pyfunction]
#[pyo3(signature = (before, after, by="line", compare="exact"))]
pub fn content_hunks(
    before: &[u8],
    after: &[u8],
    by: &str,
    compare: &str,
) -> PyResult<Vec<(String, Vec<u8>, Vec<u8>)>> {
    let diff = match by {
        "line" => jj_lib::diff_presentation::diff_by_line(
            [before, after],
            &compare_mode(compare)?,
        ),
        "word" => ContentDiff::by_word([before, after]),
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown tokenizer {by:?}, expected \"line\" or \"word\""
            )));
        }
    };
    Ok(diff
        .hunks()
        .map(|hunk| {
            let kind = match hunk.kind {
                DiffHunkKind::Matching => "matching",
                DiffHunkKind::Different => "different",
            };
            let [left, right] = hunk.contents[..].try_into().expect("two inputs");
            (
                kind.to_owned(),
                AsRef::<[u8]>::as_ref(left).to_vec(),
                AsRef::<[u8]>::as_ref(right).to_vec(),
            )
        })
        .collect())
}
