//! The bookkeeping half of jj's per-repo config directories.
//!
//! `config.rs` explains why pyjj does not *read* repo-level config: jj
//! puts it behind an id indirection so that cloning a repo cannot make
//! its aliases and merge-tool commands take effect without the user
//! opting in, and reimplementing that trust boundary casually would be a
//! security regression.
//!
//! Nothing here crosses it. These two calls read the repo *path* a config
//! directory was created for, and delete a directory whose repo is gone
//! -- which is all `jj config gc` does. Both go straight through
//! `jj_lib::secure_config`, so the file format stays jj's business: the
//! metadata is a protobuf, and decoding it by hand in Python is exactly
//! the kind of reimplementation this module avoids.

use std::path::{Path, PathBuf};

use pyo3::prelude::*;

use crate::errors::{map_py_err, JjError};

/// The repository a per-repo config directory belongs to.
///
/// `None` when the directory holds no recorded path -- an older layout,
/// or a directory that is not a config directory at all. `jj config gc`
/// skips those rather than guessing, and so should any caller.
#[pyfunction]
pub fn repo_config_repo_path(config_dir: &str) -> PyResult<Option<String>> {
    let dir = Path::new(config_dir);
    let Ok(metadata) = jj_lib::secure_config::read_metadata(dir) else {
        return Ok(None);
    };
    let path = jj_lib::secure_config::metadata_path(&metadata).map_err(map_py_err)?;
    Ok(path.map(|path| path.to_string_lossy().into_owned()))
}

/// Deletes a per-repo config directory: its `config.toml`, its
/// `metadata.binpb`, and then the directory itself.
///
/// The directory goes non-recursively, so a directory holding anything
/// else raises rather than taking a file the user put there.
#[pyfunction]
pub fn remove_repo_config_dir(config_dir: &str) -> PyResult<()> {
    jj_lib::secure_config::remove_repo_config_dir(Path::new(config_dir))
        .map_err(|err| JjError::new_err(format!("Failed to delete {config_dir}: {err}")))
}

/// Where per-repo config directories live: `<config>/jj/repos`.
///
/// Returned whether or not it exists, since `jj config gc` treats a
/// missing root as "nothing to collect" rather than an error.
#[pyfunction]
pub fn repo_configs_root_dir() -> PyResult<Option<String>> {
    let base: PathBuf = match std::env::var_os("XDG_CONFIG_HOME") {
        Some(dir) if !dir.is_empty() => PathBuf::from(dir),
        _ => match std::env::var_os("HOME") {
            Some(home) => PathBuf::from(home).join(".config"),
            None => return Ok(None),
        },
    };
    Ok(Some(
        base.join("jj").join("repos").to_string_lossy().into_owned(),
    ))
}
