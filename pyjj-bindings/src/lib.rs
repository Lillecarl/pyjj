use pyo3::prelude::*;

mod absorb;
mod aio;
mod annotate;
mod bisect;
mod bookmark;
mod checkout;
mod commit;
mod config;
mod conflicts;
mod errors;
mod evolution;
mod file;
mod fix;
mod git;
mod graph;
mod hunks;
mod ids;
mod operation;
mod oplog;
mod repo;
mod revert;
mod revset;
mod rewrite;
mod settings;
mod tag;
mod tree;
mod workspace;

use absorb::PyAbsorbStats;
use annotate::PyAnnotationLine;
use bisect::{PyBisectStep, PyBisector};
use evolution::PyEvolutionEntry;
use bookmark::PyBookmark;
use commit::{PyCommit, PyReadonlyRepo, PyVerification};
use errors::{
    BackendError, CheckoutError, GitExportError, GitFetchError, GitImportError, GitPushError,
    IndexError, JjError, RepoInitError, RepoLoadError, RevsetEvalError, RevsetParseError,
    TransactionError, WorkingCopyError, WorkspaceInitError, WorkspaceLoadError,
};
use fix::{PyFileToFix, PyFixSummary};
use graph::{PyGraphEdge, PyGraphNode};
use hunks::{PyHunk, diff_hunks};
use ids::{PyChangeId, PyCommitId, PyFileId, PySignature, PyTimestamp, PyTreeId};
use operation::PyOperation;
use oplog::PyOpAbandonStats;
use repo::{PyCommitBuilder, PyTransaction};
use rewrite::PyMoveCommitsStats;
use settings::PyUserSettings;
use tag::PyTag;
use tree::PyDiffEntry;
use workspace::PyWorkspace;

/// Python bindings for Jujutsu VCS.
#[pymodule]
fn pyjj_bindings(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("VERSION", env!("CARGO_PKG_VERSION"))?;

    // Exception hierarchy
    m.add_class::<JjError>()?;
    m.add_class::<RepoInitError>()?;
    m.add_class::<RepoLoadError>()?;
    m.add_class::<BackendError>()?;
    m.add_class::<IndexError>()?;
    m.add_class::<TransactionError>()?;
    m.add_class::<WorkspaceInitError>()?;
    m.add_class::<WorkspaceLoadError>()?;
    m.add_class::<WorkingCopyError>()?;
    m.add_class::<CheckoutError>()?;
    m.add_class::<RevsetParseError>()?;
    m.add_class::<RevsetEvalError>()?;
    m.add_class::<GitImportError>()?;
    m.add_class::<GitExportError>()?;
    m.add_class::<GitFetchError>()?;
    m.add_class::<GitPushError>()?;

    // ID and value types
    m.add_class::<PyCommitId>()?;
    m.add_class::<PyChangeId>()?;
    m.add_class::<PyTreeId>()?;
    m.add_class::<PyFileId>()?;
    m.add_class::<PyTimestamp>()?;
    m.add_class::<PySignature>()?;

    // Core types
    m.add_class::<PyUserSettings>()?;
    m.add_class::<PyBookmark>()?;
    m.add_class::<PyTag>()?;
    m.add_class::<PyCommit>()?;
    m.add_class::<PyVerification>()?;
    m.add_class::<PyDiffEntry>()?;
    m.add_class::<PyOperation>()?;
    m.add_class::<PyReadonlyRepo>()?;
    m.add_class::<PyTransaction>()?;
    m.add_class::<PyCommitBuilder>()?;
    m.add_class::<PyWorkspace>()?;
    m.add_class::<PyHunk>()?;
    m.add_class::<PyAnnotationLine>()?;
    m.add_class::<PyAbsorbStats>()?;
    m.add_class::<PyFileToFix>()?;
    m.add_class::<PyFixSummary>()?;
    m.add_class::<PyOpAbandonStats>()?;
    m.add_class::<PyGraphEdge>()?;
    m.add_class::<PyGraphNode>()?;
    m.add_class::<PyBisector>()?;
    m.add_class::<PyBisectStep>()?;
    m.add_class::<PyEvolutionEntry>()?;
    m.add_class::<PyMoveCommitsStats>()?;
    m.add_function(wrap_pyfunction!(diff_hunks, m)?)?;

    Ok(())
}
