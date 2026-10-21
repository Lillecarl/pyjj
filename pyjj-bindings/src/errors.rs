use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::pyclass_init::PyClassInitializer;

/// Creates a Python exception class inheriting from `$base`.
///
/// Exception pyclasses need an explicit `#[new]` even when only ever raised
/// from Rust via `new_err`: CPython's error-normalization machinery can call
/// the type itself (e.g. when re-raising or copying an in-flight exception),
/// and without `#[new]` that call fails with "cannot create instances",
/// masking the real error.
macro_rules! py_error {
    ($name:ident, $base:ident) => {
        // `message` lives on the base; a second copy here would shadow
        // its getter, and the stub would show an override.
        #[pyclass(extends = $base, module = "pyjj_bindings")]
        pub struct $name {}

        #[pymethods]
        impl $name {
            #[new]
            fn new(message: String) -> PyClassInitializer<Self> {
                PyClassInitializer::from($base { message }).add_subclass(Self {})
            }
        }

        impl $name {
            #[allow(dead_code)]
            pub fn new_err(msg: impl Into<String>) -> PyErr {
                PyErr::new::<$name, _>((msg.into(),))
            }
        }
    };
}

// Base exception for all jj errors — must allow subclassing
#[pyclass(subclass, extends = PyException, module = "pyjj_bindings")]
pub struct JjError {
    #[pyo3(get)]
    pub message: String,
}

#[pymethods]
impl JjError {
    #[new]
    fn new(message: String) -> Self {
        Self { message }
    }
}

impl JjError {
    pub fn new_err(msg: impl Into<String>) -> PyErr {
        PyErr::new::<JjError, _>((msg.into(),))
    }
}

// Repo / store errors
py_error!(RepoInitError, JjError);
py_error!(RepoLoadError, JjError);
py_error!(BackendError, JjError);
py_error!(RepoIndexError, JjError);
py_error!(ConfigError, JjError);

// Transaction errors
py_error!(TransactionError, JjError);
// An undo or redo of an operation another workspace made.
py_error!(CrossWorkspaceError, JjError);

// Workspace errors
py_error!(WorkspaceInitError, JjError);
py_error!(WorkspaceLoadError, JjError);

// Working copy errors
py_error!(WorkingCopyError, JjError);
py_error!(CheckoutError, JjError);

// Revset errors
py_error!(RevsetParseError, JjError);
py_error!(RevsetEvalError, JjError);

// Git errors
py_error!(GitImportError, JjError);
py_error!(GitExportError, JjError);
py_error!(GitFetchError, JjError);
py_error!(GitPushError, JjError);

/// Converts a `std::error::Error` into a [`PyErr`].
///
/// Use this for generic/caller-input errors that don't fit one of the more
/// specific categories below (e.g. malformed ID strings, bad enum-ish string
/// arguments).
pub fn map_py_err(err: impl std::error::Error) -> PyErr {
    JjError::new_err(error_chain_body(&err))
}

/// The message and its source chain, as jj prints an error: inline when
/// the chain has one link, numbered when it has several. jj_lib keeps the
/// reason in `#[source]`, so the top message alone often says only what
/// failed, not why.
pub fn error_chain_body(top: &dyn std::error::Error) -> String {
    let mut body = top.to_string();
    let mut chain: Vec<String> = Vec::new();
    let mut source = top.source();
    while let Some(error) = source {
        chain.push(error.to_string());
        source = error.source();
    }
    match chain.len() {
        0 => {}
        1 => {
            body.push_str("\nCaused by: ");
            body.push_str(&chain[0]);
        }
        _ => {
            body.push_str("\nCaused by:");
            for (index, link) in chain.iter().enumerate() {
                body.push_str(&format!("\n{}: {link}", index + 1));
            }
        }
    }
    body
}

/// Generates a `map_*_err(err) -> PyErr` helper for a specific error subclass.
macro_rules! map_err_as {
    ($fn_name:ident, $error:ident) => {
        pub fn $fn_name(err: impl std::error::Error) -> PyErr {
            $error::new_err(error_chain_body(&err))
        }
    };
}

map_err_as!(map_backend_err, BackendError);
map_err_as!(map_index_err, RepoIndexError);
map_err_as!(map_config_err, ConfigError);
map_err_as!(map_transaction_err, TransactionError);
map_err_as!(map_workspace_init_err, WorkspaceInitError);
map_err_as!(map_workspace_load_err, WorkspaceLoadError);
map_err_as!(map_repo_load_err, RepoLoadError);
map_err_as!(map_revset_parse_err, RevsetParseError);
map_err_as!(map_revset_eval_err, RevsetEvalError);
map_err_as!(map_checkout_err, CheckoutError);
map_err_as!(map_working_copy_err, WorkingCopyError);
map_err_as!(map_git_import_err, GitImportError);
map_err_as!(map_git_export_err, GitExportError);
map_err_as!(map_git_fetch_err, GitFetchError);
map_err_as!(map_git_push_err, GitPushError);

/// Extension trait for `Result<T, E>` to convert to `PyResult<T>`.
#[allow(dead_code)]
pub trait IntoPyResult<T> {
    fn map_py_err(self) -> PyResult<T>;
}

impl<T, E: std::error::Error + 'static> IntoPyResult<T> for Result<T, E> {
    fn map_py_err(self) -> PyResult<T> {
        self.map_err(map_py_err)
    }
}
