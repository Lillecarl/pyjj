use pyo3::prelude::*;

use jj_lib::object_id::ObjectId as _;
use jj_lib::operation::Operation;

use crate::errors::map_backend_err;
use crate::ids::PyTimestamp;

/// A single entry in the operation log (`jj op log`): one transaction
/// against the repo's view.
#[pyclass(name = "Operation", frozen, from_py_object)]
#[derive(Clone)]
pub struct PyOperation(pub(crate) Operation);

#[pymethods]
impl PyOperation {
    #[getter]
    fn id(&self) -> String {
        self.0.id().hex()
    }

    #[getter]
    fn description(&self) -> &str {
        &self.0.metadata().description
    }

    #[getter]
    fn hostname(&self) -> &str {
        &self.0.metadata().hostname
    }

    #[getter]
    fn username(&self) -> &str {
        &self.0.metadata().username
    }

    #[getter]
    fn start_time(&self) -> PyTimestamp {
        PyTimestamp(self.0.metadata().time.start)
    }

    #[getter]
    fn end_time(&self) -> PyTimestamp {
        PyTimestamp(self.0.metadata().time.end)
    }

    #[getter]
    fn parent_ids(&self) -> Vec<String> {
        self.0.parent_ids().iter().map(|id| id.hex()).collect()
    }

    /// The parent operations (usually one; more than one after a concurrent
    /// operation was merged).
    fn parents(&self) -> PyResult<Vec<PyOperation>> {
        let parents = pollster::block_on(self.0.parents()).map_err(map_backend_err)?;
        Ok(parents.into_iter().map(PyOperation).collect())
    }

    fn __repr__(&self) -> String {
        format!("Operation({}, {:?})", self.id(), self.description())
    }

    fn __eq__(&self, other: &Self) -> bool {
        self.0.id() == other.0.id()
    }
}
