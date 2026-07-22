use std::collections::{HashMap, HashSet};

use futures::AsyncReadExt as _;
use pyo3::prelude::*;

use jj_lib::backend::{CommitId, TreeValue};
use jj_lib::commit::Commit;
use jj_lib::matchers::{EverythingMatcher, Matcher, PrefixMatcher};
use jj_lib::merge::Merge;
use jj_lib::merged_tree::MergedTree;
use jj_lib::merged_tree_builder::MergedTreeBuilder;
use jj_lib::object_id::ObjectId as _;
use jj_lib::repo::MutableRepo;
use jj_lib::repo_path::{RepoPath, RepoPathBuf};
use jj_lib::rewrite::{self, CommitWithSelection};

use crate::commit::PyCommit;
use crate::errors::{JjError, map_backend_err};
use crate::hunks::apply_hunk_selection;
use crate::ids::PyCommitId;
use crate::repo::PyCommitBuilder;

/// Builds a matcher from `paths`: `None` matches everything; `Some(paths)`
/// matches each named path *and* everything under it if it's a directory
/// (`PrefixMatcher` -- the same "path or subtree" semantics `jj squash
/// <path>`/`jj diff <path>` use, not an exact-files-only match).
pub(crate) fn paths_matcher(paths: Option<Vec<String>>) -> PyResult<Box<dyn Matcher>> {
    match paths {
        None => Ok(Box::new(EverythingMatcher)),
        Some(paths) => {
            let repo_paths: Vec<RepoPathBuf> = paths
                .iter()
                .map(|p| {
                    RepoPathBuf::from_internal_string(p)
                        .map_err(|err| JjError::new_err(err.to_string()))
                })
                .collect::<PyResult<_>>()?;
            Ok(Box::new(PrefixMatcher::new(&repo_paths)))
        }
    }
}

/// Reads a path's raw file content from `tree`, or an empty `Vec` if the
/// path doesn't exist there (e.g. a file added/removed entirely by the
/// hunk-selected commit). Used only for hunk-level reconstruction, where
/// "no such file" on one side is a normal, expected case (unlike
/// `file::read_file`, which treats it as an error).
fn read_tree_file_bytes(tree: &MergedTree, path: &RepoPath) -> PyResult<Vec<u8>> {
    let path_str = path.as_internal_file_string();
    let value = pollster::block_on(tree.path_value(path)).map_err(map_backend_err)?;
    let resolved = value
        .into_resolved()
        .map_err(|_| JjError::new_err(format!("`{path_str}` has an unresolved conflict")))?;
    match resolved {
        Some(TreeValue::File { id, .. }) => {
            let mut reader =
                pollster::block_on(tree.store().read_file(path, &id)).map_err(map_backend_err)?;
            let mut buf = Vec::new();
            pollster::block_on(reader.read_to_end(&mut buf))
                .map_err(|err| JjError::new_err(err.to_string()))?;
            Ok(buf)
        }
        None => Ok(Vec::new()),
        Some(TreeValue::Symlink(_)) => Err(JjError::new_err(format!(
            "`{path_str}` is a symlink; hunk-level selection only supports regular files"
        ))),
        Some(TreeValue::Tree(_)) => Err(JjError::new_err(format!("`{path_str}` is a directory"))),
        Some(TreeValue::GitSubmodule(_)) => {
            Err(JjError::new_err(format!("`{path_str}` is a Git submodule")))
        }
    }
}

/// Overlays hunk-level selections on top of `base_tree`: for each `path` in
/// `hunks`, reconstructs the file's content by taking the listed hunk
/// indices (see `hunks::diff_hunks`) from `commit_tree` and leaving every
/// other hunk as it is in `parent_tree`, then writes that content as a new
/// blob and sets it in the tree. A path whose selection doesn't actually
/// change anything (empty/no-op selection) is left at whatever `base_tree`
/// already has for it.
fn apply_hunks(
    base_tree: MergedTree,
    parent_tree: &MergedTree,
    commit_tree: &MergedTree,
    hunks: HashMap<String, Vec<usize>>,
) -> PyResult<MergedTree> {
    if hunks.is_empty() {
        return Ok(base_tree);
    }
    let store = base_tree.store().clone();
    let mut builder = MergedTreeBuilder::new(base_tree);
    for (path_str, indices) in hunks {
        let repo_path = RepoPathBuf::from_internal_string(&path_str)
            .map_err(|err| JjError::new_err(err.to_string()))?;
        let before = read_tree_file_bytes(parent_tree, &repo_path)?;
        let after = read_tree_file_bytes(commit_tree, &repo_path)?;
        let selected: HashSet<usize> = indices.into_iter().collect();
        let new_content = apply_hunk_selection(&before, &after, &selected);
        if new_content == before {
            continue;
        }
        let executable = pollster::block_on(commit_tree.path_value(&repo_path))
            .ok()
            .and_then(|v| v.into_resolved().ok().flatten())
            .and_then(|tv| match tv {
                TreeValue::File { executable, .. } => Some(executable),
                _ => None,
            })
            .unwrap_or(false);
        let file_id = pollster::block_on(store.write_file(&repo_path, &mut new_content.as_slice()))
            .map_err(map_backend_err)?;
        let value: jj_lib::merge::MergedTreeValue = Merge::normal(TreeValue::File {
            id: file_id,
            executable,
            copy_id: jj_lib::backend::CopyId::placeholder(),
        });
        builder.set_or_remove(repo_path, value);
    }
    pollster::block_on(builder.write_tree()).map_err(map_backend_err)
}

/// Builds the `selected_tree`/`parent_tree` pair `jj_lib::rewrite` needs for
/// both squash and split: `parent_tree` overlaid with `commit`'s changes to
/// paths matched by `paths` (or all of `commit`'s changes if `paths` is
/// `None`), further overlaid with hunk-level reconstructions for any path
/// named in `hunks`.
fn select(
    mut_repo: &MutableRepo,
    commit: &Commit,
    paths: Option<Vec<String>>,
    hunks: Option<HashMap<String, Vec<usize>>>,
) -> PyResult<CommitWithSelection> {
    let parent_tree = pollster::block_on(commit.parent_tree(mut_repo)).map_err(map_backend_err)?;
    let commit_tree = commit.tree();
    let matcher = paths_matcher(paths)?;
    let selected_tree = pollster::block_on(rewrite::restore_tree(
        &commit_tree,
        &parent_tree,
        "commit".to_string(),
        "parent".to_string(),
        matcher.as_ref(),
    ))
    .map_err(map_backend_err)?;
    let selected_tree = match hunks {
        Some(hunks) => apply_hunks(selected_tree, &parent_tree, &commit_tree, hunks)?,
        None => selected_tree,
    };
    Ok(CommitWithSelection {
        commit: commit.clone(),
        selected_tree,
        parent_tree,
    })
}

/// `jj squash` equivalent: moves `source`'s changes (optionally restricted
/// to `paths`) into `destination`. `destination` must be a parent of
/// `source`, or a rewrite of one — same constraint `jj_lib` itself enforces.
///
/// Returns `None` if there's nothing to squash (no path restriction given
/// and `source` is already empty, or the path restriction matches no
/// changes) — matching `jj squash`'s own "nothing selected" case. Otherwise
/// returns a `CommitBuilder` for the new `destination` commit; the caller
/// still needs to set a description and `write()` it, then call
/// `rebase_descendants()` before `commit()` (source's descendants, if any,
/// need rebasing onto the squashed destination).
///
/// If the full selection was taken (no `paths`/`hunks`, or they cover
/// everything `source` changed) and `keep_emptied` is `False`, `source` is
/// abandoned — its descendants (if any) will need `rebase_descendants()`
/// same as above.
///
/// `hunks`, if given, maps path -> selected hunk indices (from
/// `hunks::diff_hunks(before, after)`, diffing that path's content in
/// `destination` against `source`) for line-level squashing of that path,
/// on top of whatever `paths` already selects whole.
pub fn squash(
    mut_repo: &mut MutableRepo,
    source: &PyCommit,
    destination: &PyCommit,
    paths: Option<Vec<String>>,
    hunks: Option<HashMap<String, Vec<usize>>>,
    keep_emptied: bool,
) -> PyResult<Option<PyCommitBuilder>> {
    let selection = select(mut_repo, &source.inner, paths, hunks)?;
    let result = pollster::block_on(rewrite::squash_commits(
        mut_repo,
        &[selection],
        &destination.inner,
        keep_emptied,
    ))
    .map_err(map_backend_err)?;
    Ok(result.map(|squashed| PyCommitBuilder::from_rust(squashed.commit_builder)))
}

/// First half of `jj split`: a `CommitBuilder` for the changes matched by
/// `paths`, plus (if `hunks` is given) the selected hunk indices of any
/// path named in `hunks` -- see `hunks::diff_hunks(before, after)`, where
/// `before`/`after` are that path's content in `target`'s parent and in
/// `target` itself. Keeps `target`'s original parents and change id. Write
/// this first, then pass the result to `split_remainder()`.
pub fn split_selected(
    mut_repo: &mut MutableRepo,
    target: &PyCommit,
    paths: Option<Vec<String>>,
    hunks: Option<HashMap<String, Vec<usize>>>,
) -> PyResult<PyCommitBuilder> {
    let selection = select(mut_repo, &target.inner, paths, hunks)?;
    let builder = mut_repo
        .rewrite_commit(&target.inner)
        .set_tree(selection.selected_tree);
    Ok(PyCommitBuilder::from_rust(builder))
}

/// Second half of `jj split`: a `CommitBuilder` for `target`'s remaining
/// changes (everything not in `first`), as a child of `first` with a fresh
/// change id (so it doesn't collide with `first`'s, which kept `target`'s
/// original one).
pub fn split_remainder(
    mut_repo: &mut MutableRepo,
    target: &PyCommit,
    first: &PyCommit,
) -> PyResult<PyCommitBuilder> {
    let builder = mut_repo
        .rewrite_commit(&target.inner)
        .set_parents(vec![first.inner.id().clone()])
        .set_tree(target.inner.tree())
        .generate_new_change_id();
    Ok(PyCommitBuilder::from_rust(builder))
}

/// `jj duplicate` equivalent: creates a copy of each commit in `targets`
/// (same tree/description/author, fresh change id) onto its own original
/// parents (or other just-duplicated commits, if one target is a parent of
/// another in `targets`) -- the originals are left untouched.
///
/// `targets` must be in reverse topological order (children before
/// parents) if it has more than one element, matching `jj duplicate`'s own
/// requirement -- an ordering violation isn't rejected outright, but a
/// target whose parent is *also* in `targets` and appears *after* it won't
/// be recognized as internal, so it'll be duplicated onto its original
/// (non-duplicated) parent instead of the new one.
///
/// Returns the new commits, in the same order as `targets`.
pub fn duplicate(mut_repo: &mut MutableRepo, targets: Vec<PyCommit>) -> PyResult<Vec<PyCommit>> {
    let target_ids: Vec<_> = targets.iter().map(|c| c.inner.id().clone()).collect();
    let stats = pollster::block_on(rewrite::duplicate_commits_onto_parents(
        mut_repo,
        &target_ids,
        &HashMap::new(),
    ))
    .map_err(map_backend_err)?;
    target_ids
        .into_iter()
        .map(|id| {
            let commit = stats.duplicated_commits.get(&id).ok_or_else(|| {
                JjError::new_err(format!("commit {} was not duplicated", id.hex()))
            })?;
            Ok(PyCommit {
                inner: commit.clone(),
                _repo: None,
            })
        })
        .collect()
}

/// `jj file chmod (executable|normal) <path>` equivalent: flips the
/// executable bit of the regular file at `path` in `commit`'s tree,
/// leaving its content untouched. Raises `JjError` if `path` isn't a
/// resolvable regular file there (symlink, directory, submodule, absent,
/// or conflicted -- none of those have an executable bit to flip).
///
/// Returns a `CommitBuilder` for the rewritten commit; the caller still
/// needs to `write()` it and `rebase_descendants()` if `commit` has any.
pub fn set_executable(
    mut_repo: &mut MutableRepo,
    commit: &PyCommit,
    path: &str,
    executable: bool,
) -> PyResult<PyCommitBuilder> {
    let repo_path =
        RepoPathBuf::from_internal_string(path).map_err(|err| JjError::new_err(err.to_string()))?;
    let tree = commit.inner.tree();
    let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
    let (id, copy_id) = match value.as_resolved() {
        Some(Some(TreeValue::File { id, copy_id, .. })) => (id.clone(), copy_id.clone()),
        _ => {
            return Err(JjError::new_err(format!(
                "`{path}` is not a resolvable regular file"
            )));
        }
    };
    let new_value = Merge::normal(TreeValue::File {
        id,
        executable,
        copy_id,
    });
    let mut builder = MergedTreeBuilder::new(tree);
    builder.set_or_remove(repo_path, new_value);
    let new_tree = pollster::block_on(builder.write_tree()).map_err(map_backend_err)?;
    let builder = mut_repo.rewrite_commit(&commit.inner).set_tree(new_tree);
    Ok(PyCommitBuilder::from_rust(builder))
}

/// `jj restore [paths] --from <src> --into <dest>` equivalent: overwrites
/// `paths` (or everything, if `None`) in `into_commit`'s tree with the
/// corresponding content from `from_commit`'s tree -- `from_commit` itself
/// is left untouched, and the two need no ancestry relationship (unlike
/// `squash`, which requires `destination` to be a parent of `source`).
/// Wraps the same `jj_lib::rewrite::restore_tree` primitive `squash`/`split`
/// use internally for path selection, just with `into_commit`'s own tree as
/// the base instead of its parent's.
///
/// Returns a `CommitBuilder` for the rewritten `into_commit`; caller still
/// needs to `write()` it and `rebase_descendants()` if it has descendants.
pub fn restore(
    mut_repo: &mut MutableRepo,
    from_commit: &PyCommit,
    into_commit: &PyCommit,
    paths: Option<Vec<String>>,
) -> PyResult<PyCommitBuilder> {
    let matcher = paths_matcher(paths)?;
    let from_tree = from_commit.inner.tree();
    let into_tree = into_commit.inner.tree();
    let new_tree = pollster::block_on(rewrite::restore_tree(
        &from_tree,
        &into_tree,
        "from".to_string(),
        "into".to_string(),
        matcher.as_ref(),
    ))
    .map_err(map_backend_err)?;
    let builder = mut_repo
        .rewrite_commit(&into_commit.inner)
        .set_tree(new_tree);
    Ok(PyCommitBuilder::from_rust(builder))
}

/// `jj abandon <rev>` equivalent: removes `commit` from history entirely
/// (not a rewrite that keeps a new version around). Any descendants get
/// rebased onto `commit`'s own parents by a later `rebase_descendants()`
/// call, and a working-copy commit pointing at it gets a fresh child of
/// those parents instead -- same as `record_abandoned_commit`'s own doc
/// comment describes. Doesn't itself call `rebase_descendants()`.
pub fn abandon(mut_repo: &mut MutableRepo, commit: &PyCommit) {
    mut_repo.record_abandoned_commit(&commit.inner);
}

/// `jj rebase -r <rev> -d <dest>` equivalent for a single commit (not its
/// descendants -- call `rebase_descendants()` afterward for that, same as
/// every other rewrite in this module). Wraps `jj_lib::rewrite::rebase_commit`,
/// which already writes the rebased commit (unlike `set_executable`, there's
/// no separate `CommitBuilder` step here).
pub fn rebase(
    mut_repo: &mut MutableRepo,
    commit: &PyCommit,
    new_parents: Vec<PyCommitId>,
) -> PyResult<PyCommit> {
    let new_parent_ids: Vec<CommitId> = new_parents.into_iter().map(|id| id.0).collect();
    let new_commit = pollster::block_on(rewrite::rebase_commit(
        mut_repo,
        commit.inner.clone(),
        new_parent_ids,
    ))
    .map_err(map_backend_err)?;
    Ok(PyCommit {
        inner: new_commit,
        _repo: None,
    })
}
