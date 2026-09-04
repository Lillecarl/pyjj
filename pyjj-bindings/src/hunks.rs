use std::collections::HashSet;

use pyo3::prelude::*;

use jj_lib::diff::{ContentDiff, DiffHunkKind};

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
    /// `(kind, content)` per line, where kind is `"context"`, `"removed"`
    /// or `"added"`. `content` keeps its trailing newline, and lacks one
    /// exactly when the file does.
    #[pyo3(get)]
    pub lines: Vec<(String, Vec<u8>)>,
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
#[pyfunction]
#[pyo3(signature = (before, after, context=3))]
pub fn unified_hunks(before: &[u8], after: &[u8], context: usize) -> Vec<PyUnifiedHunk> {
    use bstr::BStr;
    use jj_lib::diff_presentation::LineCompareMode;
    use jj_lib::diff_presentation::unified::{DiffLineType, unified_diff_hunks};
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
    unified_diff_hunks(contents, context, LineCompareMode::Exact)
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
                    let mut content = Vec::new();
                    for (_, token) in tokens {
                        content.extend_from_slice(token);
                    }
                    (kind.to_owned(), content)
                })
                .collect(),
        })
        .collect()
}
