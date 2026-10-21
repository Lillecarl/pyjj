use pyo3::prelude::*;

use jj_lib::backend::{ChangeId, CommitId, FileId, Signature, Timestamp, TreeId};
use jj_lib::object_id::ObjectId as _;

/// A commit's content hash — changes when the commit is rewritten.
#[pyclass(name = "CommitId", module = "pyjj_bindings", frozen, eq, hash, ord, from_py_object)]
#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PyCommitId(pub(crate) CommitId);

#[pymethods]
impl PyCommitId {
    #[new]
    fn new(hex: &str) -> PyResult<Self> {
        CommitId::try_from_hex(hex)
            .map(Self)
            .ok_or_else(|| super::errors::JjError::new_err(format!("invalid CommitId: {hex}")))
    }

    fn hex(&self) -> String {
        self.0.hex()
    }

    /// First `n` hex characters of the full hex ID, or all of it when `n`
    /// is longer.
    fn short(&self, n: usize) -> String {
        let mut hex = self.0.hex();
        hex.truncate(n);
        hex
    }

    fn __repr__(&self) -> String {
        format!("CommitId({})", self.0.hex())
    }

    fn __str__(&self) -> String {
        self.0.hex()
    }


}

impl From<CommitId> for PyCommitId {
    fn from(id: CommitId) -> Self {
        Self(id)
    }
}

impl From<&CommitId> for PyCommitId {
    fn from(id: &CommitId) -> Self {
        Self(id.clone())
    }
}

/// A commit's stable identity — follows the commit across rewrites.
#[pyclass(name = "ChangeId", module = "pyjj_bindings", frozen, eq, hash, ord, from_py_object)]
#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PyChangeId(pub(crate) ChangeId);

#[pymethods]
impl PyChangeId {
    /// Accepts the forward hex and the reverse hex `str()` prints. The
    /// alphabets (`0-9a-f` and `k-z`) do not overlap.
    #[new]
    fn new(hex: &str) -> PyResult<Self> {
        ChangeId::try_from_hex(hex)
            .or_else(|| ChangeId::try_from_reverse_hex(hex))
            .map(Self)
            .ok_or_else(|| super::errors::JjError::new_err(format!("invalid ChangeId: {hex}")))
    }

    fn hex(&self) -> String {
        self.0.hex()
    }

    /// The "reverse" hex form (uses letters z-k instead of 0-9a-f), which is
    /// the conventional display format for change IDs.
    fn reverse_hex(&self) -> String {
        self.0.reverse_hex()
    }

    fn __repr__(&self) -> String {
        format!("ChangeId({})", self.0.reverse_hex())
    }

    fn __str__(&self) -> String {
        self.0.reverse_hex()
    }


}

impl From<ChangeId> for PyChangeId {
    fn from(id: ChangeId) -> Self {
        Self(id)
    }
}

/// A tree object identifier.
#[pyclass(name = "TreeId", module = "pyjj_bindings", frozen, eq, hash, ord, from_py_object)]
#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PyTreeId(pub(crate) TreeId);

#[pymethods]
impl PyTreeId {
    #[new]
    fn new(hex: &str) -> PyResult<Self> {
        TreeId::try_from_hex(hex)
            .map(Self)
            .ok_or_else(|| super::errors::JjError::new_err(format!("invalid TreeId: {hex}")))
    }

    fn hex(&self) -> String {
        self.0.hex()
    }

    fn __repr__(&self) -> String {
        format!("TreeId({})", self.0.hex())
    }

}

/// A file content identifier.
#[pyclass(name = "FileId", module = "pyjj_bindings", frozen, eq, hash, ord, from_py_object)]
#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PyFileId(pub(crate) FileId);

#[pymethods]
impl PyFileId {
    #[new]
    fn new(hex: &str) -> PyResult<Self> {
        FileId::try_from_hex(hex)
            .map(Self)
            .ok_or_else(|| super::errors::JjError::new_err(format!("invalid FileId: {hex}")))
    }

    fn hex(&self) -> String {
        self.0.hex()
    }

    fn __repr__(&self) -> String {
        format!("FileId({})", self.0.hex())
    }

}

/// A timestamp with millisecond precision and a timezone offset.
#[pyclass(name = "Timestamp", module = "pyjj_bindings", frozen, eq, hash, ord, from_py_object)]
#[derive(Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PyTimestamp(pub(crate) Timestamp);

#[pymethods]
impl PyTimestamp {
    #[new]
    fn new(millis_since_epoch: i64, tz_offset_minutes: i32) -> Self {
        use jj_lib::backend::MillisSinceEpoch;
        Self(Timestamp {
            timestamp: MillisSinceEpoch(millis_since_epoch),
            tz_offset: tz_offset_minutes,
        })
    }

    #[getter]
    fn millis_since_epoch(&self) -> i64 {
        self.0.timestamp.0
    }

    #[getter]
    fn tz_offset_minutes(&self) -> i32 {
        self.0.tz_offset
    }

    fn __repr__(&self) -> String {
        format!("Timestamp({}, {}min)", self.0.timestamp.0, self.0.tz_offset)
    }


}

/// The name, email, and timestamp for a commit author or committer.
#[pyclass(name = "Signature", module = "pyjj_bindings", frozen, eq, hash, from_py_object)]
#[derive(Clone, PartialEq, Eq, Hash)]
pub struct PySignature(pub(crate) Signature);

#[pymethods]
impl PySignature {
    #[new]
    fn new(name: String, email: String, timestamp: PyTimestamp) -> Self {
        Self(Signature {
            name,
            email,
            timestamp: timestamp.0,
        })
    }

    #[getter]
    fn name(&self) -> &str {
        &self.0.name
    }

    #[getter]
    fn email(&self) -> &str {
        &self.0.email
    }

    #[getter]
    fn timestamp(&self) -> PyTimestamp {
        PyTimestamp(self.0.timestamp)
    }

    fn __repr__(&self) -> String {
        format!("Signature({} <{}>)", self.0.name, self.0.email)
    }


}

impl From<Signature> for PySignature {
    fn from(sig: Signature) -> Self {
        Self(sig)
    }
}
