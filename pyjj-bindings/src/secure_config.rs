//! jj's per-repo and per-workspace config directories.
//!
//! jj keeps this config outside the repository: `.jj/repo/config-id`
//! holds a hex id, and `<config>/jj/repos/<id>/` holds the config file
//! plus a `metadata.binpb` recording which repository the directory was
//! created for. `.jj` is not part of a git clone, so a clone carries no
//! config and cannot make its aliases or merge-tool commands take
//! effect; the metadata is what stops a copied or reused id from
//! pointing somewhere else.
//!
//! Everything here goes through `jj_lib::secure_config` rather than
//! reimplementing the layout. Minting an id and writing a `config.toml`
//! by hand leaves out the metadata, and jj then treats the directory as
//! absent -- which is exactly what pyjj used to do, so `jj` silently
//! ignored config `pyjj config set --repo` had written.

use std::path::{Path, PathBuf};

use pyo3::prelude::*;

use crate::errors::{map_py_err, JjError};

/// Which of jj's two id-indirected scopes a call means.
///
/// The two differ in the directory that holds the id, the name of that
/// file, and the directory the config lands in -- all of them jj's
/// spelling, not a choice made here.
pub(crate) fn scoped(
    workspace_root: &Path,
    repo_path: &Path,
    kind: &str,
) -> PyResult<(jj_lib::secure_config::SecureConfig, PathBuf)> {
    let root = crate::config::secure_config_root(match kind {
        "repo" => "repos",
        "workspace" => "workspaces",
        other => {
            return Err(JjError::new_err(format!(
                "unknown config scope `{other}`"
            )))
        }
    })
    .ok_or_else(|| JjError::new_err("no platform config directory"))?;
    let config = match kind {
        "repo" => jj_lib::secure_config::SecureConfig::new_repo(repo_path.to_path_buf()),
        _ => jj_lib::secure_config::SecureConfig::new_workspace(workspace_root.join(".jj")),
    };
    Ok((config, root))
}

/// The config file for a repo or workspace, as jj would find it.
///
/// With `create`, jj mints an id and writes the metadata when there is
/// none yet -- the same call `jj config set --repo` makes, so a
/// directory pyjj creates is one jj reads. Without it, a repository
/// that has never had scoped config returns `None` and nothing is
/// written.
#[pyfunction]
#[pyo3(signature = (workspace_root, repo_path, kind, create=false))]
pub fn secure_config_file(
    workspace_root: &str,
    repo_path: &str,
    kind: &str,
    create: bool,
) -> PyResult<Option<String>> {
    use rand_chacha::rand_core::SeedableRng as _;

    let (config, root) = scoped(Path::new(workspace_root), Path::new(repo_path), kind)?;
    // Seeded exactly as jj's own `ConfigEnv::new` seeds it, down to
    // the env var: a test that pins the seed gets the same config id
    // from either tool.
    let mut rng = match std::env::var("JJ_RANDOMNESS_SEED")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
    {
        Some(seed) => rand_chacha::ChaCha20Rng::seed_from_u64(seed),
        None => rand::make_rng(),
    };
    let loaded = if create {
        config.load_config(&mut rng, &root)
    } else {
        config.maybe_load_config(&mut rng, &root)
    }
    .map_err(map_py_err)?;
    Ok(loaded
        .config_file
        .map(|path| path.to_string_lossy().into_owned()))
}

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
