use pyo3::prelude::*;

use jj_lib::op_store::RefTarget;
use jj_lib::ref_name::RefName;

use crate::ids::PyCommitId;

/// A local bookmark: a name pointing at one or more commits.
///
/// More than one target id means the bookmark is conflicted (e.g. moved
/// differently by concurrent operations) — check `has_conflict`.
#[pyclass(name = "Bookmark", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyBookmark {
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub target_ids: Vec<PyCommitId>,
    #[pyo3(get)]
    pub has_conflict: bool,
}

impl PyBookmark {
    pub(crate) fn from_target(name: &RefName, target: &RefTarget) -> Self {
        Self {
            name: name.as_str().to_string(),
            target_ids: target.added_ids().map(PyCommitId::from).collect(),
            has_conflict: target.has_conflict(),
        }
    }
}

#[pymethods]
impl PyBookmark {
    fn __repr__(&self) -> String {
        let conflict = if self.has_conflict { "True" } else { "False" };
        format!("Bookmark({}, conflict={conflict})", self.name)
    }

    fn __eq__(&self, other: &Self) -> bool {
        self.name == other.name
            && self.has_conflict == other.has_conflict
            && self.target_ids == other.target_ids
    }
}
