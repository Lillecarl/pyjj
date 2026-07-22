use pyo3::prelude::*;

use jj_lib::conflicts::{
    ConflictMarkerStyle, ConflictMaterializeOptions, choose_materialized_conflict_marker_len,
    try_materialize_file_conflict_value, update_from_content,
};
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
    let Some(old_file_ids) = value.to_file_merge() else {
        return Err(JjError::new_err(format!(
            "`{path}` is conflicted, but not as a plain file -- can't resolve from text"
        )));
    };

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
            "`{path}` is conflicted, but not as a plain file -- can't resolve from text"
        ))
    })?;
    let marker_len = choose_materialized_conflict_marker_len(&materialized.contents);

    let new_file_ids = pollster::block_on(update_from_content(
        &old_file_ids,
        store,
        &repo_path,
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
    let new_value = match new_file_ids.into_resolved() {
        Ok(Some(file_id)) => jj_lib::merge::Merge::normal(jj_lib::backend::TreeValue::File {
            id: file_id,
            executable: materialized.executable.unwrap_or(false),
            copy_id: materialized
                .copy_id
                .clone()
                .unwrap_or_else(jj_lib::backend::CopyId::placeholder),
        }),
        Ok(None) => jj_lib::merge::Merge::absent(),
        Err(new_file_ids) => value.with_new_file_ids(&new_file_ids),
    };

    let mut builder = MergedTreeBuilder::new(tree.clone());
    builder.set_or_remove(repo_path, new_value);
    let new_tree = pollster::block_on(builder.write_tree()).map_err(map_backend_err)?;

    let commit_builder = mut_repo.rewrite_commit(&commit.inner).set_tree(new_tree);
    Ok(PyCommitBuilder::from_rust(commit_builder))
}
