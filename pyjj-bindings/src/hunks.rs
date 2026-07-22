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
