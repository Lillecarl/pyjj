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
    /// The commits the bookmark points at. More than one means it is
    /// conflicted.
    #[pyo3(get)]
    pub target_ids: Vec<PyCommitId>,
    /// The commits a conflicted bookmark moved *away* from. Empty
    /// unless `has_conflict`. jj prints these as the `-` side when it
    /// lists a conflicted bookmark, against `target_ids` as the `+`
    /// side.
    #[pyo3(get)]
    pub removed_ids: Vec<PyCommitId>,
    #[pyo3(get)]
    pub has_conflict: bool,
}

impl PyBookmark {
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

/// A remote-tracking bookmark: a name on a remote, pointing at commits.
///
/// jj spells these `name@remote`, and prints them beside local
/// bookmarks wherever a commit's refs are listed. A colocated
/// repository has a `git` remote, so every exported bookmark has one of
/// these alongside it.
#[pyclass(name = "RemoteBookmark", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyRemoteBookmark {
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub remote: String,
    #[pyo3(get)]
    pub target_ids: Vec<PyCommitId>,
    /// The commits a conflicted remote bookmark moved *away* from,
    /// against `target_ids` as the side it moved to. Empty unless
    /// `has_conflict`.
    #[pyo3(get)]
    pub removed_ids: Vec<PyCommitId>,
    #[pyo3(get)]
    pub has_conflict: bool,
    /// Whether the local bookmark of the same name follows this one.
    #[pyo3(get)]
    pub tracked: bool,
}

#[pymethods]
impl PyRemoteBookmark {
    /// `name@remote`, the way jj writes it.
    #[getter]
    fn symbol(&self) -> String {
        format!("{}@{}", self.name, self.remote)
    }

    fn __repr__(&self) -> String {
        format!("RemoteBookmark({})", self.symbol())
    }
}
