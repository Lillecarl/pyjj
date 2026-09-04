use pyo3::prelude::*;
use std::collections::HashMap;

use jj_lib::conflicts::{
    ConflictMarkerStyle, ConflictMaterializeOptions, choose_materialized_conflict_marker_len,
    try_materialize_file_conflict_value, update_from_content,
};
use jj_lib::merge::Merge;
use jj_lib::merged_tree_builder::MergedTreeBuilder;
use jj_lib::repo::MutableRepo;
use jj_lib::repo_path::RepoPathBuf;

use crate::commit::PyCommit;
use crate::errors::{JjError, map_backend_err, map_py_err};
use crate::repo::PyCommitBuilder;
use crate::settings::PyUserSettings;

/// Renders the conflict at `path` in `commit`'s tree as conflict-marker
/// text -- the same thing you'd see if you looked at the file in a real
/// jj working copy while it's conflicted. Marker style comes from
/// `settings`' `ui.conflict-marker-style` config (`"diff"` by default,
/// matching jj's own default).
///
/// Raises `JjError` if `path` isn't actually conflicted, or is a conflict
/// jj can't materialize as text (e.g. a file/directory conflict).
pub fn materialize_conflict(
    commit: &PyCommit,
    settings: &PyUserSettings,
    path: &str,
) -> PyResult<Vec<u8>> {
    let repo_path =
        RepoPathBuf::from_internal_string(path).map_err(|err| JjError::new_err(err.to_string()))?;
    let tree = commit.inner.tree();
    let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
    if value.as_resolved().is_some() {
        return Err(JjError::new_err(format!("`{path}` is not conflicted")));
    }
    let store = tree.store();
    let materialized = pollster::block_on(try_materialize_file_conflict_value(
        store,
        &repo_path,
        &value,
        tree.labels(),
    ))
    .map_err(map_backend_err)?
    .ok_or_else(|| {
        JjError::new_err(format!(
            "`{path}` is conflicted, but not as a plain file (e.g. a file/directory \
                     conflict) -- can't materialize as text"
        ))
    })?;

    let marker_style: ConflictMarkerStyle = settings
        .0
        .get("ui.conflict-marker-style")
        .map_err(map_py_err)?;
    let options = ConflictMaterializeOptions {
        marker_style,
        marker_len: None,
        merge: store.merge_options().clone(),
    };
    let bytes = jj_lib::conflicts::materialize_merge_result_to_bytes(
        &materialized.contents,
        &materialized.labels,
        &options,
    );
    Ok(bytes.into())
}

/// Core of both `resolve_conflict` entry points: parse edited
/// conflict-marker text back into new file ids for one conflicted path
/// (`update_from_content`), and turn that into the tree value to store --
/// fully resolved, absent, or still conflicted with updated content.
fn resolve_file_value(
    tree: &jj_lib::merged_tree::MergedTree,
    repo_path: &RepoPathBuf,
    value: jj_lib::merge::MergedTreeValue,
    content: &[u8],
) -> PyResult<jj_lib::merge::MergedTreeValue> {
    let Some(old_file_ids) = value.to_file_merge() else {
        return Err(JjError::new_err(format!(
            "`{}` is conflicted, but not as a plain file -- can't resolve from text",
            repo_path.as_internal_file_string()
        )));
    };

    let store = tree.store();
    let materialized = pollster::block_on(try_materialize_file_conflict_value(
        store,
        repo_path,
        &value,
        tree.labels(),
    ))
    .map_err(map_backend_err)?
    .ok_or_else(|| {
        JjError::new_err(format!(
            "`{}` is conflicted, but not as a plain file -- can't resolve from text",
            repo_path.as_internal_file_string()
        ))
    })?;
    let marker_len = choose_materialized_conflict_marker_len(&materialized.contents);

    let new_file_ids = pollster::block_on(update_from_content(
        &old_file_ids,
        store,
        repo_path,
        content,
        marker_len,
    ))
    .map_err(map_backend_err)?;
    // `with_new_file_ids` requires its argument to have the same arity as
    // `value` -- true only while still conflicted. Once resolved,
    // `new_file_ids` collapses to a single side, so the resolved
    // `TreeValue` has to be built directly instead (mirrors how
    // `local_working_copy.rs`'s own snapshot-time conflict resolution
    // handles this same fork).
    Ok(match new_file_ids.into_resolved() {
        Ok(Some(file_id)) => Merge::normal(jj_lib::backend::TreeValue::File {
            id: file_id,
            executable: materialized.executable.unwrap_or(false),
            copy_id: materialized
                .copy_id
                .clone()
                .unwrap_or_else(jj_lib::backend::CopyId::placeholder),
        }),
        Ok(None) => Merge::absent(),
        Err(new_file_ids) => value.with_new_file_ids(&new_file_ids),
    })
}

/// Applies edited conflict-marker text (as produced by
/// `materialize_conflict`, then hand-edited -- fully resolving some or all
/// markers, or left alone) back onto `commit`'s tree at `path`, returning a
/// `CommitBuilder` for the rewritten commit.
///
/// If `content` no longer contains valid conflict markers (of the marker
/// length jj would have used to materialize this exact conflict), the
/// path resolves to a plain file. If markers remain (possibly for only
/// some of the original conflicts, if there were several in the file),
/// the path stays conflicted with the updated content -- matching real
/// `jj`'s "partially resolve, re-edit later" workflow. Passing back
/// exactly what `materialize_conflict` returned, unedited, is a no-op.
///
/// Raises `JjError` if `path` isn't actually conflicted.
pub fn resolve_conflict(
    mut_repo: &mut MutableRepo,
    commit: &PyCommit,
    path: &str,
    content: &[u8],
) -> PyResult<PyCommitBuilder> {
    let repo_path =
        RepoPathBuf::from_internal_string(path).map_err(|err| JjError::new_err(err.to_string()))?;
    let tree = commit.inner.tree();
    let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
    if value.as_resolved().is_some() {
        return Err(JjError::new_err(format!("`{path}` is not conflicted")));
    }

    let new_value = resolve_file_value(&tree, &repo_path, value, content)?;

    let mut builder = MergedTreeBuilder::new(tree.clone());
    builder.set_or_remove(repo_path, new_value);
    let new_tree = pollster::block_on(builder.write_tree()).map_err(map_backend_err)?;

    let commit_builder = mut_repo.rewrite_commit(&commit.inner).set_tree(new_tree);
    Ok(PyCommitBuilder::from_rust(commit_builder))
}

/// Multi-path variant of `resolve_conflict`: resolves every path in
/// `selections` ({path: edited marker text}) in ONE tree rewrite, so the
/// rewritten commit's committer timestamp moves once regardless of how
/// many paths were resolved. This is what `jj resolve`'s merge-tool flow
/// needs: real `jj` applies every tool result to a single
/// `MergedTreeBuilder` and calls `rewrite_commit(..).set_tree(..)` once.
pub fn resolve_conflicts(
    mut_repo: &mut MutableRepo,
    commit: &PyCommit,
    selections: HashMap<String, Vec<u8>>,
) -> PyResult<PyCommitBuilder> {
    if selections.is_empty() {
        // Still rewrite: real jj rewrites the commit even when the merge
        // tool changed nothing (the committer-timestamp bump records the
        // attempt).
        let builder = mut_repo.rewrite_commit(&commit.inner);
        return Ok(PyCommitBuilder::from_rust(builder));
    }
    let tree = commit.inner.tree();
    let mut builder = MergedTreeBuilder::new(tree.clone());
    for (path_str, content) in selections {
        let repo_path = RepoPathBuf::from_internal_string(&path_str)
            .map_err(|err| JjError::new_err(err.to_string()))?;
        let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
        if value.as_resolved().is_some() {
            return Err(JjError::new_err(format!("`{path_str}` is not conflicted")));
        }
        let new_value = resolve_file_value(&tree, &repo_path, value, &content)?;
        builder.set_or_remove(repo_path, new_value);
    }
    let new_tree = pollster::block_on(builder.write_tree()).map_err(map_backend_err)?;
    let commit_builder = mut_repo.rewrite_commit(&commit.inner).set_tree(new_tree);
    Ok(PyCommitBuilder::from_rust(commit_builder))
}

/// The raw sides of the file conflict at `path`, exactly as an external
/// 3-way merge tool receives them: `(base, left, right, executable)` --
/// base/left/right are the remove/add contents (`$base`/`$left`/`$right`
/// in merge-args; base may be empty for add/add-style conflicts), and
/// `executable` is the bit a resolved file must keep. Raises `JjError`
/// unless `path` is a resolvable two-sided plain-file conflict, mirroring
/// real `jj resolve`'s own restrictions (more than two sides, or
/// conflicting executable bits, are rejected there too).
#[allow(clippy::type_complexity)]
pub fn conflict_sides(
    commit: &PyCommit,
    path: &str,
) -> PyResult<(Vec<u8>, Vec<u8>, Vec<u8>, bool)> {
    let repo_path =
        RepoPathBuf::from_internal_string(path).map_err(|err| JjError::new_err(err.to_string()))?;
    let tree = commit.inner.tree();
    let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
    match value.clone().into_resolved() {
        Err(_conflict) => {
            let store = tree.store();
            let materialized =
                pollster::block_on(try_materialize_file_conflict_value(
                    store,
                    &repo_path,
                    &value,
                    tree.labels(),
                ))
                .map_err(map_backend_err)?
                .ok_or_else(|| {
                    JjError::new_err(format!(
                        "`{path}` is conflicted, but not as a plain file -- no 3-way \
                                 merge sides to expose"
                    ))
                })?;
            if materialized.ids.num_sides() > 2 {
                return Err(JjError::new_err(format!(
                    "`{path}` has a {}-sided conflict; only 3-way (two-sided) conflicts \
                             can be resolved with a merge tool",
                    materialized.ids.num_sides()
                )));
            }
            if materialized.executable.is_none() {
                return Err(JjError::new_err(format!(
                    "`{path}` has conflicting executable bits; not resolvable via a \
                             merge tool"
                )));
            }
            let get_side = |get: fn(&Merge<bstr::BString>, usize) -> Option<&bstr::BString>| -> Vec<u8> {
                get(&materialized.contents, 0)
                    .map(|b| b.to_vec())
                    .unwrap_or_default()
            };
            let base = get_side(Merge::get_remove);
            let left = get_side(Merge::get_add);
            let right = materialized
                .contents
                .get_add(1)
                .map(|b| b.to_vec())
                .unwrap_or_default();
            Ok((base, left, right, materialized.executable.unwrap_or(false)))
        }
        Ok(Some(_)) => Err(JjError::new_err(format!("`{path}` is not conflicted"))),
        Ok(None) => Err(JjError::new_err(format!("`{path}` does not exist"))),
    }
}

/// Pick one side of each file conflict at `paths`, like `jj resolve
/// --tool :ours` (side 0) / `:theirs` (side 1). The chosen side's
/// `FileId` (and executable bit / `copy_id`) is kept verbatim, exactly
/// as `jj`'s `pick_conflict_side` does -- no re-hashing of file
/// contents. Raises `JjError` unless every path is a resolvable
/// two-sided plain-file conflict, mirroring real `jj resolve`'s own
/// restrictions.
pub fn pick_conflict_sides(
    mut_repo: &mut MutableRepo,
    commit: &PyCommit,
    paths: Vec<String>,
    side: usize,
) -> PyResult<PyCommitBuilder> {
    if side > 1 {
        return Err(JjError::new_err(format!(
            "side index {side} out of range; only 0 (:ours) and 1 (:theirs) are supported"
        )));
    }
    if paths.is_empty() {
        let builder = mut_repo.rewrite_commit(&commit.inner);
        return Ok(PyCommitBuilder::from_rust(builder));
    }
    let tree = commit.inner.tree();
    let mut builder = MergedTreeBuilder::new(tree.clone());
    for path_str in paths {
        let repo_path = RepoPathBuf::from_internal_string(&path_str)
            .map_err(|err| JjError::new_err(err.to_string()))?;
        let value = pollster::block_on(tree.path_value(&repo_path)).map_err(map_backend_err)?;
        if value.as_resolved().is_some() {
            return Err(JjError::new_err(format!("`{path_str}` is not conflicted")));
        }
        let materialized = pollster::block_on(try_materialize_file_conflict_value(
            tree.store(),
            &repo_path,
            &value,
            tree.labels(),
        ))
        .map_err(map_backend_err)?
        .ok_or_else(|| {
            JjError::new_err(format!(
                "`{path_str}` is conflicted, but not as a plain file -- no 3-way \
                 merge sides to expose"
            ))
        })?;
        if materialized.ids.num_sides() > 2 {
            return Err(JjError::new_err(format!(
                "`{path_str}` has a {}-sided conflict; only 3-way (two-sided) conflicts \
                 can be resolved with a merge tool",
                materialized.ids.num_sides()
            )));
        }
        if materialized.executable.is_none() {
            return Err(JjError::new_err(format!(
                "`{path_str}` has conflicting executable bits; not resolvable via a \
                 merge tool"
            )));
        }
        if side >= materialized.ids.num_sides() {
            return Err(JjError::new_err(format!(
                "`{path_str}` does not have side {side}"
            )));
        }
        let file_id = materialized.ids.get_add(side).unwrap().clone();
        let executable = materialized.executable.unwrap_or(false);
        let copy_id = materialized
            .copy_id
            .clone()
            .unwrap_or_else(jj_lib::backend::CopyId::placeholder);
        let new_value = match file_id {
            Some(id) => Merge::normal(jj_lib::backend::TreeValue::File {
                id,
                executable,
                copy_id,
            }),
            None => Merge::absent(),
        };
        builder.set_or_remove(repo_path, new_value);
    }
    let new_tree = pollster::block_on(builder.write_tree()).map_err(map_backend_err)?;
    let commit_builder = mut_repo.rewrite_commit(&commit.inner).set_tree(new_tree);
    Ok(PyCommitBuilder::from_rust(commit_builder))
}

/// Every conflicted path in `commit`'s tree, with the numbers `jj
/// status` reports about each.
///
/// `sides` is the conflict's arity after simplification, and `adds` how
/// many of those sides are present -- the difference is deletions, which
/// jj counts separately because they interfere with neither `jj resolve`
/// nor a diff. `objects` names anything that is not a plain file, since
/// those do interfere: an executable, a symlink, a directory or a git
/// submodule.
///
/// Formatting the sentence is the caller's; this settles the counts,
/// which is the part that has to agree with jj.
pub fn conflicted_paths(commit: &PyCommit) -> PyResult<Vec<(String, usize, usize, Vec<String>)>> {
    use jj_lib::backend::TreeValue;

    let mut out = Vec::new();
    for (path, value) in commit.inner.tree().conflicts() {
        let conflict = value.map_err(map_backend_err)?.simplify();
        let sides = conflict.num_sides();
        let adds = conflict.adds().flatten().count();
        let mut objects: Vec<String> = Vec::new();
        for term in conflict.removes().flatten().chain(conflict.adds().flatten()) {
            let name = match term {
                TreeValue::File { executable: false, .. } => continue,
                TreeValue::File { executable: true, .. } => "an executable",
                TreeValue::Symlink(_) => "a symlink",
                TreeValue::Tree(_) => "a directory",
                TreeValue::GitSubmodule(_) => "a git submodule",
                _ => continue,
            };
            if !objects.iter().any(|seen| seen == name) {
                objects.push(name.to_string());
            }
        }
        objects.sort();
        out.push((
            path.as_internal_file_string().to_string(),
            sides,
            adds,
            objects,
        ));
    }
    Ok(out)
}
