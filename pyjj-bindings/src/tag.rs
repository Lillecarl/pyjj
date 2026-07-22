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
    #[pyo3(get)]
    pub has_conflict: bool,
}

impl PyTag {
    pub(crate) fn from_target(name: &RefName, target: &RefTarget) -> Self {
        Self {
            name: name.as_str().to_string(),
            target_ids: target.added_ids().map(PyCommitId::from).collect(),
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
