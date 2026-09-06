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
use jj_lib::repo::{MutableRepo, Repo as _};
use jj_lib::repo_path::{RepoPath, RepoPathBuf};
use jj_lib::rewrite::{
    self, CommitWithSelection, EmptyBehavior, MoveCommitsLocation, MoveCommitsTarget,
    RebaseOptions, RewriteRefsOptions,
};

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

/// `jj squash --tool`: the same squash, with the moved changes chosen by a
/// diff editor rather than by paths. The tool edits a copy of the source's
/// own diff -- left is the source's parent, right is the source -- and
/// whatever the right side holds afterwards is what moves. See
/// `overlay_contents` for the selection model.
pub fn squash_edited(
    mut_repo: &mut MutableRepo,
    source: &PyCommit,
    destination: &PyCommit,
    selections: HashMap<String, Option<Vec<u8>>>,
    keep_emptied: bool,
) -> PyResult<Option<PyCommitBuilder>> {
    let parent_tree =
        pollster::block_on(source.inner.parent_tree(mut_repo)).map_err(map_backend_err)?;
    let selected_tree = overlay_contents(
        parent_tree.clone(),
        Some(&source.inner.tree()),
        selections,
    )?;
    let selection = CommitWithSelection {
        commit: source.inner.clone(),
        selected_tree,
        parent_tree,
    };
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
    reject_root(mut_repo, target.inner.id())?;
    let selection = select(mut_repo, &target.inner, paths, hunks)?;
    let builder = mut_repo
        .rewrite_commit(&target.inner)
        .set_tree(selection.selected_tree);
    Ok(PyCommitBuilder::from_rust(builder))
}

/// Overlays per-path content overrides onto `base_tree`: `Some(bytes)`
/// writes that exact content (executable bit inherited from `commit_tree`
/// when the path exists there), `None` removes the path. This is the
/// diff-editor result model — the tool edits copies of the changed files,
/// and whatever exists in its output directory afterwards becomes the new
/// state, deletions and additions included.
fn overlay_contents(
    base_tree: MergedTree,
    commit_tree: Option<&MergedTree>,
    selections: HashMap<String, Option<Vec<u8>>>,
) -> PyResult<MergedTree> {
    if selections.is_empty() {
        return Ok(base_tree);
    }
    let store = base_tree.store().clone();
    let mut builder = MergedTreeBuilder::new(base_tree);
    for (path_str, content) in selections {
        let repo_path = RepoPathBuf::from_internal_string(&path_str)
            .map_err(|err| JjError::new_err(err.to_string()))?;
        match content {
            None => {
                builder.set_or_remove(repo_path, Merge::absent());
            }
            Some(bytes) => {
                let executable = commit_tree
                    .and_then(|tree| {
                        pollster::block_on(tree.path_value(&repo_path))
                            .ok()
                            .and_then(|v| v.into_resolved().ok().flatten())
                    })
                    .and_then(|tv| match tv {
                        TreeValue::File { executable, .. } => Some(executable),
                        _ => None,
                    })
                    .unwrap_or(false);
                let file_id =
                    pollster::block_on(store.write_file(&repo_path, &mut bytes.as_slice()))
                        .map_err(map_backend_err)?;
                let value: jj_lib::merge::MergedTreeValue = Merge::normal(TreeValue::File {
                    id: file_id,
                    executable,
                    copy_id: jj_lib::backend::CopyId::placeholder(),
                });
                builder.set_or_remove(repo_path, value);
            }
        }
    }
    pollster::block_on(builder.write_tree()).map_err(map_backend_err)
}

/// `split_selected()` for diff-editor flows: `selections` maps changed
/// paths to their post-editing content (`None` = dropped/reverted). The
/// first half's tree is `target`'s PARENT tree overlaid with exactly these
/// contents — so unselected paths stay at parent state, and partially
/// edited files carry the edited bytes verbatim.
pub fn split_selected_edited(
    mut_repo: &mut MutableRepo,
    target: &PyCommit,
    selections: HashMap<String, Option<Vec<u8>>>,
) -> PyResult<PyCommitBuilder> {
    reject_root(mut_repo, target.inner.id())?;
    let parent_tree =
        pollster::block_on(target.inner.parent_tree(mut_repo)).map_err(map_backend_err)?;
    let edited = overlay_contents(parent_tree, Some(&target.inner.tree()), selections)?;
    let builder = mut_repo
        .rewrite_commit(&target.inner)
        .set_tree(edited);
    Ok(PyCommitBuilder::from_rust(builder))
}

/// Rewrites `commit` with per-path content overrides applied on top of its
/// own tree (`diffedit`'s model: edit the diff between two revisions and
/// apply the result to the destination side).
pub fn edit_commit_tree(
    mut_repo: &mut MutableRepo,
    commit: &PyCommit,
    selections: HashMap<String, Option<Vec<u8>>>,
) -> PyResult<PyCommitBuilder> {
    let edited = overlay_contents(commit.inner.tree(), Some(&commit.inner.tree()), selections)?;
    let builder = mut_repo.rewrite_commit(&commit.inner).set_tree(edited);
    Ok(PyCommitBuilder::from_rust(builder))
}

/// Second half of `jj split`: a `CommitBuilder` for `target`'s remaining
/// changes (everything not in `first`), as a child of `first`.
///
/// `new_change_id` decides which half keeps `target`'s change id, and jj
/// gives it to whichever half stays where `target` was. A plain split
/// leaves `first` in place, so the remainder takes a fresh id (the
/// default). `jj split --onto/-A/-B` moves `first` away instead, so the
/// remainder keeps the original -- pass `false` there, and clear the
/// rewrite source on `first` so only one commit claims to rewrite
/// `target`.
pub fn split_remainder(
    mut_repo: &mut MutableRepo,
    target: &PyCommit,
    first: &PyCommit,
    new_change_id: bool,
) -> PyResult<PyCommitBuilder> {
    let builder = mut_repo
        .rewrite_commit(&target.inner)
        .set_parents(vec![first.inner.id().clone()])
        .set_tree(target.inner.tree());
    let builder = if new_change_id {
        builder.generate_new_change_id()
    } else {
        builder
    };
    Ok(PyCommitBuilder::from_rust(builder))
}

/// Second half of `jj split --parallel`: the same remaining changes, but
/// as a *sibling* of `first` rather than its child.
///
/// The tree cannot simply be `target`'s, the way the chained form's can.
/// A child of `first` shows the rest as a diff against `first`; a sibling
/// hangs from `target`'s own parents, so its tree has to be `target`'s
/// with the selected changes undone. That is what merging `target`'s tree
/// with the inverted parent->selected diff produces
/// (`cli/src/commands/split.rs` builds it the same way).
pub fn split_remainder_parallel(
    mut_repo: &mut MutableRepo,
    target: &PyCommit,
    first: &PyCommit,
) -> PyResult<PyCommitBuilder> {
    let parent_tree = pollster::block_on(target.inner.parent_tree(mut_repo)).map_err(map_backend_err)?;
    let target_tree = target.inner.tree();
    let selected_diff = jj_lib::merge::Diff::new(
        (parent_tree, "parents of split revision".to_string()),
        (first.inner.tree(), "selected changes for split".to_string()),
    );
    let new_tree = pollster::block_on(MergedTree::merge(Merge::from_diffs(
        (target_tree, "split revision".to_string()),
        [selected_diff.invert()],
    )))
    .map_err(map_backend_err)?;
    let builder = mut_repo
        .rewrite_commit(&target.inner)
        .set_parents(target.inner.parent_ids().to_vec())
        .set_tree(new_tree)
        .generate_new_change_id();
    Ok(PyCommitBuilder::from_rust(builder))
}

/// `jj abandon --restore-descendants`: abandon `targets` and move their
/// descendants down without touching the descendants' contents.
///
/// A plain abandon *rebases* the descendants, so each one's diff is
/// replayed against its new parent and its content can change. Restoring
/// descendants *reparents* them instead: the tree is kept verbatim and
/// only the parent edge moves, which is what the flag is for. There is no
/// `RebaseOptions` for this -- the choice lives in the per-commit
/// callback, so this drives `transform_descendants` the way
/// `cli/src/commands/abandon.rs` does.
///
/// Returns the number of descendants that moved.
pub fn abandon_restoring_descendants(
    mut_repo: &mut MutableRepo,
    targets: Vec<PyCommitId>,
    delete_abandoned_bookmarks: bool,
) -> PyResult<usize> {
    let roots: Vec<CommitId> = targets.into_iter().map(|id| id.0).collect();
    for id in &roots {
        reject_root(mut_repo, id)?;
    }
    let to_abandon: HashSet<CommitId> = roots.iter().cloned().collect();
    let options = rewrite::RewriteRefsOptions {
        delete_abandoned_bookmarks,
    };
    let moved = std::cell::Cell::new(0usize);
    pollster::block_on(mut_repo.transform_descendants_with_options(
        roots.clone(),
        &jj_lib::revset::RevsetExpression::none(),
        &HashMap::new(),
        &options,
        async |rewriter| {
            if to_abandon.contains(rewriter.old_commit().id()) {
                rewriter.abandon();
            } else {
                rewriter.reparent().write().await?;
                moved.set(moved.get() + 1);
            }
            Ok(())
        },
    ))
    .map_err(map_backend_err)?;
    Ok(moved.into_inner())
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
    for id in &target_ids {
        reject_root(mut_repo, id)?;
    }
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
    from_commit: Option<&PyCommit>,
    into_commit: &PyCommit,
    paths: Option<Vec<String>>,
) -> PyResult<PyCommitBuilder> {
    let matcher = paths_matcher(paths)?;
    // No source is `jj restore`'s own default: restore from the merge of
    // the destination's parents. The first parent alone would report a
    // merge commit as changing everything its other parents contributed.
    let from_tree = match from_commit {
        Some(commit) => commit.inner.tree(),
        None => pollster::block_on(into_commit.inner.parent_tree(mut_repo))
            .map_err(map_backend_err)?,
    };
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
pub fn abandon(mut_repo: &mut MutableRepo, commit: &PyCommit) -> PyResult<()> {
    reject_root(mut_repo, commit.inner.id())?;
    mut_repo.record_abandoned_commit(&commit.inner);
    Ok(())
}

/// `jj`'s `check_rewritable`: refuse to rewrite a commit the user has
/// declared immutable.
///
/// The set is whatever `immutable()` resolves to, which is jj's own
/// `::(immutable_heads() | root())` unless the user redefined
/// `immutable_heads()`. In a repository with no remote that collapses to
/// the root commit alone; with a pushed trunk or a tag it covers real
/// shared history, which is the point -- the check exists to stop a
/// rewrite that would strand everybody else.
///
/// Raises on the first immutable commit found, with jj's own wording.
/// The hints jj adds are left out: they are CLI presentation, and pyjj
/// raises an exception rather than rendering an error.
///
/// This is policy, not safety. `reject_root` below is the safety half,
/// and stays even where this check runs, because a caller reaching a
/// jj_lib assertion crashes the interpreter.
pub fn check_rewritable(
    mut_repo: &MutableRepo,
    workspace_root: &std::path::Path,
    workspace_name: &jj_lib::ref_name::WorkspaceNameBuf,
    settings: &crate::settings::PyUserSettings,
    ids: Vec<CommitId>,
) -> PyResult<()> {
    use futures::TryStreamExt as _;

    if ids.is_empty() {
        return Ok(());
    }
    // `immutable()` comes from jj's bundled `revsets.toml`, so it only
    // exists when `settings` loaded config. A caller who opted out asked
    // for a check whose definition they turned off; say that, rather
    // than letting a bare "function doesn't exist" parse error out.
    let immutable = crate::revset::resolve_revset(
        mut_repo,
        workspace_root,
        workspace_name,
        settings,
        "immutable()",
    )
    .map_err(|err| {
        JjError::new_err(format!(
            "cannot check for immutable commits: the `immutable()` revset alias is \
             unavailable, which happens when UserSettings was built with \
             load_config=False ({err})"
        ))
    })?;
    let to_rewrite = jj_lib::revset::RevsetExpression::commits(ids);
    let evaluated = immutable
        .intersection(&to_rewrite)
        .evaluate(mut_repo)
        .map_err(crate::errors::map_py_err)?;
    let found = pollster::block_on(evaluated.stream().try_next())
        .map_err(crate::errors::map_py_err)?;
    let Some(id) = found else {
        return Ok(());
    };
    let short = &id.hex()[..12];
    Err(JjError::new_err(
        if &id == mut_repo.store().root_commit_id() {
            format!("The root commit {short} is immutable")
        } else {
            format!("Commit {short} is immutable")
        },
    ))
}

/// Refuse to rewrite the root commit.
///
/// jj_lib asserts rather than returning an error here, and an assertion
/// failure inside a native extension aborts the process instead of
/// raising something Python can catch. `jj` never reaches those
/// assertions because its CLI refuses immutable commits first, and the
/// root commit is always immutable. The message matches jj's so the two
/// tools fail the same way.
pub fn reject_root(mut_repo: &MutableRepo, id: &CommitId) -> PyResult<()> {
    if id == mut_repo.store().root_commit_id() {
        return Err(crate::errors::JjError::new_err(format!(
            "The root commit {} is immutable",
            &id.hex()[..12]
        )));
    }
    Ok(())
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
    reject_root(mut_repo, commit.inner.id())?;
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

/// Result of `Transaction.move_commits()`: counts mirroring `jj rebase`'s
/// own post-rebase summary line.
#[pyclass(name = "MoveCommitsStats", frozen, get_all)]
pub struct PyMoveCommitsStats {
    /// Number of commits in the target set that were themselves rebased.
    num_rebased_targets: u32,
    /// Number of descendant commits (outside the target set) rebased as a
    /// consequence.
    num_rebased_descendants: u32,
    /// Number of commits skipped because they were already in place.
    num_skipped_rebases: u32,
    /// Number of commits abandoned for having become empty, which only
    /// `skip_emptied` produces.
    num_abandoned_empty: u32,
}

/// `jj rebase` equivalent covering every one of its destination modes in one
/// call, via `jj_lib::rewrite::move_commits` -- the same unified primitive
/// the `jj` CLI itself composes `-r`/`-s`/`-b` and `-d`/`-A`/`-B` from
/// (`cli/src/commands/rebase.rs`), so none of that graph-surgery logic (nor
/// its edge cases -- cycles, divergent merges, `simplify_ancestor_merge`)
/// is reimplemented here.
///
/// Exactly one of `target_commit_ids` (specific revisions, `jj rebase -r`
/// -- must be in reverse topological order if there's more than one) /
/// `target_root_ids` (roots whose descendants are pulled along too, `jj
/// rebase -s`/`-b`) must be non-empty; the other must be empty.
///
/// `new_parent_ids`/`new_child_ids` give the target's new location:
/// `new_child_ids` empty means a plain `-d <new_parent_ids>` rebase;
/// non-empty `new_child_ids` splices the moved commits in as parents of
/// those children too (`-A`/`-B`) -- computing the right ids for each
/// insert-after/insert-before/both combination (mirroring
/// `cli_util::compute_commit_location`) is the caller's job, not this
/// binding's; this only performs the move once a destination is chosen.
///
/// Already rebases the target's descendants internally -- but still call
/// `rebase_descendants()` before `commit()` for anything else pending in
/// this transaction, same rule as every other rewrite here.
///
/// `skip_emptied` and `simplify_parents` are `jj rebase`'s flags of those
/// names. `keep_divergent` is that flag too, and it defaults the other
/// way round: `jj rebase` abandons a divergent commit that the
/// destination already holds with identical contents, but every other
/// caller of this -- duplicate, split, squash -- keeps one, so the
/// caller that wants jj's rebase behaviour asks for it.
pub fn move_commits(
    mut_repo: &mut MutableRepo,
    target_commit_ids: Vec<PyCommitId>,
    target_root_ids: Vec<PyCommitId>,
    new_parent_ids: Vec<PyCommitId>,
    new_child_ids: Vec<PyCommitId>,
    skip_emptied: bool,
    keep_divergent: bool,
    simplify_parents: bool,
) -> PyResult<PyMoveCommitsStats> {
    if target_commit_ids.is_empty() == target_root_ids.is_empty() {
        return Err(JjError::new_err(
            "move_commits: exactly one of target_commit_ids/target_root_ids must be non-empty",
        ));
    }
    for id in target_commit_ids.iter().chain(target_root_ids.iter()) {
        reject_root(mut_repo, &id.0)?;
    }
    let target = if !target_commit_ids.is_empty() {
        MoveCommitsTarget::Commits(target_commit_ids.into_iter().map(|id| id.0).collect())
    } else {
        MoveCommitsTarget::Roots(target_root_ids.into_iter().map(|id| id.0).collect())
    };
    let loc = MoveCommitsLocation {
        new_parent_ids: new_parent_ids.into_iter().map(|id| id.0).collect(),
        new_child_ids: new_child_ids.into_iter().map(|id| id.0).collect(),
        target,
    };
    let options = RebaseOptions {
        empty: if skip_emptied {
            EmptyBehavior::AbandonNewlyEmpty
        } else {
            EmptyBehavior::Keep
        },
        rewrite_refs: RewriteRefsOptions {
            delete_abandoned_bookmarks: false,
        },
        simplify_ancestor_merge: simplify_parents,
    };
    let mut computed =
        pollster::block_on(rewrite::compute_move_commits(mut_repo, &loc)).map_err(map_backend_err)?;
    if !keep_divergent {
        let abandoned = pollster::block_on(rewrite::find_duplicate_divergent_commits(
            mut_repo,
            &loc.new_parent_ids,
            &loc.target,
        ))
        .map_err(map_backend_err)?;
        computed.record_to_abandon(abandoned.iter().map(|commit| commit.id().clone()));
    }
    let stats = pollster::block_on(computed.apply(mut_repo, &options)).map_err(map_backend_err)?;
    Ok(PyMoveCommitsStats {
        num_rebased_targets: stats.num_rebased_targets,
        num_rebased_descendants: stats.num_rebased_descendants,
        num_skipped_rebases: stats.num_skipped_rebases,
        num_abandoned_empty: stats.num_abandoned_empty,
    })
}
