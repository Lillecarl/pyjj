use futures::AsyncReadExt as _;
use pyo3::prelude::*;

use jj_lib::backend::MergedTreeValueExt as _;
use jj_lib::backend::TreeValue;
use jj_lib::fileset::{FilesetAliasesMap, FilesetDiagnostics, FilesetExpression, FilesetParseContext};
use jj_lib::ui_path::RepoPathUiConverter;

use crate::commit::PyCommit;
use crate::errors::{JjError, map_backend_err};
use crate::settings::PyUserSettings;

/// Reads the content of the file (or symlink target) at `path` within
/// `commit`'s tree.
///
/// Raises `JjError` if the path doesn't exist, is a directory or Git
/// submodule, or has an unresolved conflict (render it with
/// `materialize_conflict()` instead).
pub fn read_file(commit: &PyCommit, path: &str) -> PyResult<Vec<u8>> {
    let repo_path = crate::tree::repo_path(path)?;
    let tree = commit.inner.tree();
    let value = crate::tree::tree_value(&tree, &repo_path)?;
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
        let repo_path = crate::tree::repo_path(&path)?;
        let value = crate::tree::tree_value(&tree, &repo_path)?;
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

/// The kind of tree entry at `path` in `commit`'s tree, for callers
/// that must tell the cases apart -- `jj file edit` refuses
/// directories, symlinks/submodules, and non-file conflicts with
/// different messages each.
///
/// One of `"file"`, `"symlink"`, `"dir"`, `"submodule"`, `"absent"`,
/// `"file-conflict"` (every side a file or absent -- materializable as
/// text), or `"other-conflict"`.
pub fn file_kind(commit: &PyCommit, path: &str) -> PyResult<String> {
    let repo_path = crate::tree::repo_path(path)?;
    let tree = commit.inner.tree();
    let value = crate::tree::tree_value(&tree, &repo_path)?;
    let kind = match value.as_resolved() {
        Some(Some(TreeValue::File { .. })) => "file",
        Some(Some(TreeValue::Symlink(_))) => "symlink",
        Some(Some(TreeValue::Tree(_))) => "dir",
        Some(Some(TreeValue::GitSubmodule(_))) => "submodule",
        Some(None) => "absent",
        None if value.to_file_merge().is_some() => "file-conflict",
        None => "other-conflict",
    };
    Ok(kind.to_string())
}

/// Whether `path` names a regular file, executable file, or symlink (not a
/// directory/submodule/conflict/absence) within `commit`'s tree.
pub fn file_exists(commit: &PyCommit, path: &str) -> PyResult<bool> {
    let repo_path = crate::tree::repo_path(path)?;
    let tree = commit.inner.tree();
    let value = crate::tree::tree_value(&tree, &repo_path)?;
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
    let repo_path = crate::tree::repo_path(path)?;
    let tree = commit.inner.tree();
    let value = crate::tree::tree_value(&tree, &repo_path)?;
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

/// `jj`'s fileset matching for commands that take `<FILESETS>` (`file
/// delete`, ...): parse each pattern the way `WorkspaceCommandHelper::
/// parse_union_filesets` does (bare paths fall back to exact paths,
/// `fileset-aliases` from `settings` expand) against a converter rooted
/// at `workspace_root`, and list every path in `commit`'s tree they
/// match.
///
/// Returns `(matched, unmatched_explicit)`: paths present in the tree,
/// plus the explicit (non-pattern) paths that matched nothing -- jj
/// warns about those (`No matching entries for paths: ...`) without
/// failing. Parse diagnostics (jj prints them as `In fileset
/// expression` warnings) are dropped: a headless library has nowhere
/// good to print them, and a bad pattern surfaces as a parse error at
/// this point anyway.
pub fn match_filesets(
    commit: &PyCommit,
    settings: &PyUserSettings,
    workspace_root: &str,
    patterns: Vec<String>,
) -> PyResult<(Vec<String>, Vec<String>)> {
    let path_converter = RepoPathUiConverter::Fs {
        cwd: std::path::PathBuf::from(workspace_root),
        base: std::path::PathBuf::from(workspace_root),
    };
    let aliases_map: FilesetAliasesMap =
        crate::revset::load_aliases_map(settings.0.config(), "fileset-aliases");
    let context = FilesetParseContext {
        aliases_map: &aliases_map,
        path_converter: &path_converter,
    };
    let mut diagnostics = FilesetDiagnostics::new();
    let mut expressions = Vec::with_capacity(patterns.len());
    for pattern in &patterns {
        let expression =
            jj_lib::fileset::parse_maybe_bare(&mut diagnostics, pattern, &context)
                .map_err(|err| JjError::new_err(err.to_string()))?;
        expressions.push(expression);
    }
    let expression = FilesetExpression::union_all(expressions);
    let matcher = expression.to_matcher();
    let tree = commit.inner.tree();
    let mut matched = Vec::new();
    for (path, value) in tree.entries_matching(matcher.as_ref()) {
        value.map_err(map_backend_err)?;
        matched.push(path.as_internal_file_string().to_string());
    }
    let mut unmatched = Vec::new();
    for path in expression.explicit_paths() {
        let value =
            pollster::block_on(tree.path_value(path)).map_err(map_backend_err)?;
        if value.is_absent() {
            unmatched.push(path.as_internal_file_string().to_string());
        }
    }
    Ok((matched, unmatched))
}
