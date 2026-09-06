use futures::AsyncReadExt as _;
use pyo3::prelude::*;

use jj_lib::backend::TreeValue;
use jj_lib::repo_path::RepoPathBuf;

use crate::commit::PyCommit;
use crate::errors::{JjError, map_backend_err};

/// Reads the content of the file (or symlink target) at `path` within
/// `commit`'s tree.
///
/// Raises `JjError` if the path doesn't exist, is a directory or Git
/// submodule, or has an unresolved conflict (conflict materialization isn't
/// implemented yet — see AGENTS.md).
pub fn read_file(commit: &PyCommit, path: &str) -> PyResult<Vec<u8>> {
    let repo_path =
        RepoPathBuf::from_internal_string(path).map_err(|err| JjError::new_err(err.to_string()))?;
    let tree = commit.inner.tree();
    let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
    let resolved = value
        .into_resolved()
        .map_err(|_| JjError::new_err(format!("`{path}` has an unresolved conflict")))?;

    match resolved {
        Some(TreeValue::File { id, .. }) => {
            let mut reader = pollster::block_on(commit.inner.store().read_file(&repo_path, &id))
                .map_err(map_backend_err)?;
            let mut buf = Vec::new();
            pollster::block_on(reader.read_to_end(&mut buf))
                .map_err(|err| JjError::new_err(err.to_string()))?;
            Ok(buf)
        }
        Some(TreeValue::Symlink(id)) => {
            let target = pollster::block_on(commit.inner.store().read_symlink(&repo_path, &id))
                .map_err(map_backend_err)?;
            Ok(target.into_bytes())
        }
        Some(TreeValue::Tree(_)) => Err(JjError::new_err(format!("`{path}` is a directory"))),
        Some(TreeValue::GitSubmodule(_)) => {
            Err(JjError::new_err(format!("`{path}` is a Git submodule")))
        }
        None => Err(JjError::new_err(format!("`{path}` does not exist"))),
    }
}

/// The bytes at each of `paths` in `commit`'s merged parent tree, keyed
/// by path. `None` where the parent tree does not hold that path as a
/// readable file.
///
/// `jj restore` (with no `--from`) and `jj diffedit -r` both edit the
/// diff between a commit and the *merge* of its parents, and a diff
/// editor needs the content of both sides. The first parent alone would
/// report a merge commit as changing everything its other parents
/// contributed, which is why this is not `read_file` on a parent.
pub fn parent_contents(
    commit: &PyCommit,
    repo: &crate::commit::PyReadonlyRepo,
    paths: Vec<String>,
) -> PyResult<std::collections::HashMap<String, Option<Vec<u8>>>> {
    let tree = pollster::block_on(commit.inner.parent_tree(repo.inner.as_ref()))
        .map_err(map_backend_err)?;
    let mut out = std::collections::HashMap::new();
    for path in paths {
        let repo_path = RepoPathBuf::from_internal_string(&path)
            .map_err(|err| JjError::new_err(err.to_string()))?;
        let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
        let content = match value.as_resolved() {
            Some(Some(TreeValue::File { id, .. })) => {
                let mut reader =
                    pollster::block_on(commit.inner.store().read_file(&repo_path, id))
                        .map_err(map_backend_err)?;
                let mut buf = Vec::new();
                pollster::block_on(reader.read_to_end(&mut buf))
                    .map_err(|err| JjError::new_err(err.to_string()))?;
                Some(buf)
            }
            Some(Some(TreeValue::Symlink(id))) => Some(
                pollster::block_on(commit.inner.store().read_symlink(&repo_path, id))
                    .map_err(map_backend_err)?
                    .into_bytes(),
            ),
            _ => None,
        };
        out.insert(path, content);
    }
    Ok(out)
}

/// Whether `path` names a regular file, executable file, or symlink (not a
/// directory/submodule/conflict/absence) within `commit`'s tree.
pub fn file_exists(commit: &PyCommit, path: &str) -> PyResult<bool> {
    let repo_path =
        RepoPathBuf::from_internal_string(path).map_err(|err| JjError::new_err(err.to_string()))?;
    let tree = commit.inner.tree();
    let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
    Ok(matches!(
        value.as_resolved(),
        Some(Some(TreeValue::File { .. })) | Some(Some(TreeValue::Symlink(_)))
    ))
}

/// Whether `path` is a regular file with the executable bit set in
/// `commit`'s tree. `None` if `path` isn't a resolvable regular file at
/// all (symlink, directory, submodule, absent, or an unresolved conflict)
/// -- unlike `read_file()`/`file_exists()`, this never raises for those
/// cases, since "not an executable file" covers all of them uniformly.
pub fn is_executable(commit: &PyCommit, path: &str) -> PyResult<Option<bool>> {
    let repo_path =
        RepoPathBuf::from_internal_string(path).map_err(|err| JjError::new_err(err.to_string()))?;
    let tree = commit.inner.tree();
    let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
    Ok(match value.as_resolved() {
        Some(Some(TreeValue::File { executable, .. })) => Some(*executable),
        _ => None,
    })
}

/// `jj file list [paths]` equivalent: every path in `commit`'s tree (files,
/// symlinks, Git submodules -- not directories, which aren't separate tree
/// entries), optionally restricted to `paths` the same "path or subtree"
/// way `diff()`/`squash()` are (see `rewrite::paths_matcher`). Conflicted
/// paths are still listed (matching real `jj file list`, which shows them
/// with a conflict marker rather than omitting them) -- use
/// `Commit.read_file()`/`is_executable()` on a specific path if you need to
/// know its resolution status.
pub fn list_files(commit: &PyCommit, paths: Option<Vec<String>>) -> PyResult<Vec<String>> {
    let matcher = crate::rewrite::paths_matcher(paths)?;
    let tree = commit.inner.tree();
    tree.entries_matching(matcher.as_ref())
        .map(|(path, value)| {
            value.map_err(map_backend_err)?;
            Ok(path.as_internal_file_string().to_string())
        })
        .collect()
}
