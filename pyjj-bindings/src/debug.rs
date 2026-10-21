//! `jj debug`: jj-lib internals rendered with the `Debug` formatting jj's
//! `cli/src/commands/debug/` uses, so the text matches jj's byte for byte.
//! Each function returns what jj writes to stdout.

use std::fmt::Write as _;
use std::path::PathBuf;

use futures::AsyncReadExt as _;
use futures::StreamExt as _;
use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::backend::{CommitId, FileId, SymlinkId, TreeId, TreeValue};
use jj_lib::default_index::{DefaultIndexStore, DefaultReadonlyIndex};
use jj_lib::fileset::{self, FilesetAliasesMap, FilesetDiagnostics, FilesetExpression, FilesetParseContext};
use jj_lib::local_working_copy::LocalWorkingCopy;
use jj_lib::merge::Merge;
use jj_lib::object_id::ObjectId as _;
use jj_lib::op_store::{OperationId, ViewId};
use jj_lib::operation::Operation;
use jj_lib::repo::{Repo as _, RepoLoader};
use jj_lib::repo_path::RepoPathBuf;
use jj_lib::revset::{self, RevsetExtensions, SymbolResolver};
use jj_lib::stacked_table::{TableSegment as _, TableStore};
use jj_lib::ui_path::RepoPathUiConverter;
use jj_lib::working_copy::WorkingCopy as _;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{JjError, map_backend_err, map_revset_eval_err};
use crate::operation::PyOperation;
use crate::settings::PyUserSettings;
use crate::workspace::PyWorkspace;

fn err(e: impl std::fmt::Display) -> PyErr {
    JjError::new_err(e.to_string())
}

fn converter(workspace_root: &str, cwd: &str) -> RepoPathUiConverter {
    RepoPathUiConverter::Fs {
        cwd: PathBuf::from(cwd),
        base: PathBuf::from(workspace_root),
    }
}

/// `parse_union_filesets`: every pattern, bare paths allowed; none means
/// all files.
fn union_filesets(
    settings: &PyUserSettings,
    path_converter: &RepoPathUiConverter,
    patterns: &[String],
) -> PyResult<FilesetExpression> {
    if patterns.is_empty() {
        return Ok(FilesetExpression::all());
    }
    let aliases_map: FilesetAliasesMap =
        crate::revset::load_aliases_map(settings.0.config(), "fileset-aliases");
    let context = FilesetParseContext {
        aliases_map: &aliases_map,
        path_converter,
    };
    let mut diagnostics = FilesetDiagnostics::new();
    let expressions = patterns
        .iter()
        .map(|p| fileset::parse_maybe_bare(&mut diagnostics, p, &context).map_err(err))
        .collect::<PyResult<Vec<_>>>()?;
    Ok(FilesetExpression::union_all(expressions))
}

/// The head operation, read without loading the repo: `debug index` and
/// `debug reindex` must not build an index as a side effect.
fn head_operation(loader: &RepoLoader) -> PyResult<Operation> {
    let heads = pollster::block_on(loader.op_heads_store().get_op_heads()).map_err(err)?;
    let [head] = heads.as_slice() else {
        return Err(err("Concurrent operations; run any jj command to merge them first"));
    };
    pollster::block_on(loader.load_operation(head)).map_err(err)
}

fn default_index_store(loader: &RepoLoader) -> PyResult<&DefaultIndexStore> {
    let index_store = loader.index_store();
    index_store
        .downcast_ref::<DefaultIndexStore>()
        .ok_or_else(|| err(format!("Unsupported index type '{}'", index_store.name())))
}

/// `jj debug revset`.
#[pyfunction]
#[pyo3(signature = (repo, settings, revision, *, no_resolve=false, no_optimize=false))]
pub fn debug_revset(
    repo: &PyReadonlyRepo,
    settings: &PyUserSettings,
    revision: &str,
    no_resolve: bool,
    no_optimize: bool,
) -> PyResult<String> {
    let mut out = String::new();
    let expression =
        crate::revset::parse_revset(repo.inner.store(), &repo.workspace_root, &repo.workspace_name, settings, revision)?;
    writeln!(out, "-- Parsed:\n{expression:#?}\n").unwrap();
    if no_resolve && no_optimize {
        return Ok(out);
    } else if no_resolve {
        let expression = revset::optimize(expression);
        writeln!(out, "-- Optimized:\n{expression:#?}\n").unwrap();
        return Ok(out);
    }

    let repo_ref = repo.inner.as_ref();
    let extensions = RevsetExtensions::new();
    let symbol_resolver = SymbolResolver::new(repo_ref, extensions.symbol_resolvers());
    let (mut expression, other_repos) = expression
        .resolve_user_expression(repo_ref, &symbol_resolver)
        .map_err(map_revset_eval_err)?
        .into_inner();
    writeln!(out, "-- Resolved:\n{expression:#?}\n").unwrap();
    if !no_optimize {
        expression = revset::optimize(expression);
        writeln!(out, "-- Optimized:\n{expression:#?}\n").unwrap();
    }
    let backend_expression = expression.to_backend_expression(repo_ref);
    writeln!(out, "-- Backend:\n{backend_expression:#?}\n").unwrap();
    let revset = expression
        .evaluate_unoptimized(repo_ref, &other_repos)
        .map_err(map_revset_eval_err)?;
    writeln!(out, "-- Evaluated:\n{revset:#?}\n").unwrap();
    writeln!(out, "-- Commit IDs:").unwrap();
    let ids: Vec<CommitId> =
        pollster::block_on(revset.stream().try_collect()).map_err(map_revset_eval_err)?;
    for id in ids {
        writeln!(out, "{}", id.hex()).unwrap();
    }
    Ok(out)
}

/// `jj debug fileset`.
#[pyfunction]
pub fn debug_fileset(
    settings: &PyUserSettings,
    workspace_root: &str,
    cwd: &str,
    path: String,
) -> PyResult<String> {
    let expression = union_filesets(settings, &converter(workspace_root, cwd), &[path])?;
    let matcher = expression.to_matcher();
    Ok(format!("-- Parsed:\n{expression:#?}\n\n-- Matcher:\n{matcher:#?}\n"))
}

/// `jj debug tree`: the entries of `commit`'s tree, or of the tree `id`
/// at `dir`, that `paths` match.
#[pyfunction]
#[pyo3(signature = (repo, settings, cwd, paths, commit=None, id=None, dir=None))]
#[allow(clippy::too_many_arguments)]
pub fn debug_tree(
    repo: &PyReadonlyRepo,
    settings: &PyUserSettings,
    cwd: &str,
    paths: Vec<String>,
    commit: Option<&PyCommit>,
    id: Option<String>,
    dir: Option<String>,
) -> PyResult<String> {
    let path_converter = converter(&repo.workspace_root.to_string_lossy(), cwd);
    let matcher = union_filesets(settings, &path_converter, &paths)?.to_matcher();
    let mut out = String::new();
    let mut write = |path: RepoPathBuf, value: &dyn std::fmt::Debug| {
        writeln!(out, "{}: {value:?}", path_converter.format_file_path(&path)).unwrap();
    };
    if let Some(id) = id {
        let tree_id = TreeId::try_from_hex(&id).ok_or_else(|| err("Invalid tree id"))?;
        let dir = match dir {
            Some(dir) => path_converter.parse_file_path(&dir).map_err(err)?,
            None => RepoPathBuf::root(),
        };
        let tree = pollster::block_on(repo.inner.store().get_tree(dir, &tree_id))
            .map_err(map_backend_err)?;
        for (path, value) in tree.entries_matching(matcher.as_ref()) {
            let value: jj_lib::backend::BackendResult<_> = Ok(Merge::normal(value));
            write(path, &value);
        }
    } else {
        let commit = commit.ok_or_else(|| err("debug_tree needs a commit or a tree id"))?;
        for (path, value) in commit.inner.tree().entries_matching(matcher.as_ref()) {
            write(path, &value);
        }
    }
    Ok(out)
}

/// `jj debug copy-detection`: `source -> target` per copy Git reports
/// between each parent and `commit`.
#[pyfunction]
pub fn debug_copy_detection(repo: &PyReadonlyRepo, commit: &PyCommit) -> PyResult<String> {
    let store = repo.inner.store();
    let mut out = String::new();
    for parent_id in commit.inner.parent_ids() {
        let mut records = store
            .get_copy_records(None, parent_id, commit.inner.id())
            .map_err(map_backend_err)?;
        while let Some(result) = pollster::block_on(records.next()) {
            if let Ok(record) = result {
                writeln!(
                    out,
                    "{} -> {}",
                    record.source.as_internal_file_string(),
                    record.target.as_internal_file_string()
                )
                .unwrap();
            }
        }
    }
    Ok(out)
}

/// `jj debug object commit`.
#[pyfunction]
pub fn debug_object_commit(workspace: &PyWorkspace, id: &str) -> PyResult<String> {
    let commit_id = CommitId::try_from_hex(id)
        .ok_or_else(|| err(format!(r#"Invalid hex commit id: "{id}""#)))?;
    let ws = workspace.lock();
    let commit = pollster::block_on(ws.repo_loader().store().get_commit_async(&commit_id))
        .map_err(map_backend_err)?;
    Ok(format!("{:#?}\n", commit.store_commit()))
}

/// `jj debug object operation`.
#[pyfunction]
pub fn debug_object_operation(workspace: &PyWorkspace, id: &str) -> PyResult<String> {
    let op_id = OperationId::try_from_hex(id)
        .ok_or_else(|| err(format!(r#"Invalid hex operation id: "{id}""#)))?;
    let ws = workspace.lock();
    let operation =
        pollster::block_on(ws.repo_loader().op_store().read_operation(&op_id)).map_err(err)?;
    Ok(format!("{operation:#?}\n"))
}

/// `jj debug object view`: by view id, or by `op`'s view.
#[pyfunction]
#[pyo3(signature = (workspace, id=None, op=None))]
pub fn debug_object_view(
    workspace: &PyWorkspace,
    id: Option<&str>,
    op: Option<&PyOperation>,
) -> PyResult<String> {
    let view_id = match (op, id) {
        (Some(op), _) => op.0.view_id().clone(),
        (None, Some(id)) => ViewId::try_from_hex(id)
            .ok_or_else(|| err(format!(r#"Invalid hex view id: "{id}""#)))?,
        (None, None) => return Err(err("debug_object_view needs an id or an operation")),
    };
    let ws = workspace.lock();
    let view = pollster::block_on(ws.repo_loader().op_store().read_view(&view_id)).map_err(err)?;
    Ok(format!("{view:#?}\n"))
}

/// The resolved tree value at `path` in `commit`, for `debug object
/// file/symlink/tree --revision`.
fn resolved_value(commit: &PyCommit, path: &RepoPathBuf) -> PyResult<Option<TreeValue>> {
    let value = pollster::block_on(commit.inner.tree().path_value(path)).map_err(map_backend_err)?;
    Ok(value.into_resolved().ok().flatten())
}

fn internal_path(path: &str) -> PyResult<RepoPathBuf> {
    RepoPathBuf::from_internal_string(path).map_err(err)
}

/// `jj debug object file`: the file's bytes, by id or from `commit`.
#[pyfunction]
#[pyo3(signature = (workspace, path, id=None, commit=None))]
pub fn debug_object_file(
    workspace: &PyWorkspace,
    path: &str,
    id: Option<&str>,
    commit: Option<&PyCommit>,
) -> PyResult<Vec<u8>> {
    let path = internal_path(path)?;
    let file_id = match (commit, id) {
        (Some(commit), _) => match resolved_value(commit, &path)? {
            Some(TreeValue::File { id, .. }) => id,
            _ => return Err(err("The path is not a single file in the commit")),
        },
        (None, Some(id)) => FileId::try_from_hex(id)
            .ok_or_else(|| err(format!(r#"Invalid hex file id: "{id}""#)))?,
        (None, None) => return Err(err("debug_object_file needs an id or a commit")),
    };
    let ws = workspace.lock();
    let mut contents = pollster::block_on(ws.repo_loader().store().read_file(&path, &file_id))
        .map_err(map_backend_err)?;
    let mut buf = vec![];
    pollster::block_on(contents.read_to_end(&mut buf)).map_err(err)?;
    Ok(buf)
}

/// `jj debug object symlink`: the link target, by id or from `commit`.
#[pyfunction]
#[pyo3(signature = (workspace, path, id=None, commit=None))]
pub fn debug_object_symlink(
    workspace: &PyWorkspace,
    path: &str,
    id: Option<&str>,
    commit: Option<&PyCommit>,
) -> PyResult<String> {
    let path = internal_path(path)?;
    let symlink_id = match (commit, id) {
        (Some(commit), _) => match resolved_value(commit, &path)? {
            Some(TreeValue::Symlink(id)) => id,
            _ => return Err(err("The path is not a single symlink in the commit")),
        },
        (None, Some(id)) => SymlinkId::try_from_hex(id)
            .ok_or_else(|| err(format!(r#"Invalid hex symlink id: "{id}""#)))?,
        (None, None) => return Err(err("debug_object_symlink needs an id or a commit")),
    };
    let ws = workspace.lock();
    let target = pollster::block_on(ws.repo_loader().store().read_symlink(&path, &symlink_id))
        .map_err(map_backend_err)?;
    Ok(format!("{target}\n"))
}

/// `jj debug object tree`: the tree object at `dir`, by id or from
/// `commit`.
#[pyfunction]
#[pyo3(signature = (workspace, dir, id=None, commit=None))]
pub fn debug_object_tree(
    workspace: &PyWorkspace,
    dir: &str,
    id: Option<&str>,
    commit: Option<&PyCommit>,
) -> PyResult<String> {
    let dir = internal_path(dir)?;
    let tree_id = match (commit, id) {
        (Some(commit), _) => match resolved_value(commit, &dir)? {
            Some(TreeValue::Tree(id)) => id,
            _ => return Err(err("The path is not a single tree in the commit")),
        },
        (None, Some(id)) => TreeId::try_from_hex(id)
            .ok_or_else(|| err(format!(r#"Invalid hex tree id: "{id}""#)))?,
        (None, None) => return Err(err("debug_object_tree needs an id or a commit")),
    };
    let ws = workspace.lock();
    let tree = pollster::block_on(ws.repo_loader().store().get_tree(dir, &tree_id))
        .map_err(map_backend_err)?;
    Ok(format!("{:#?}\n", tree.data()))
}

/// `jj debug index`: statistics of the index at the head operation.
#[pyfunction]
pub fn debug_index(workspace: &PyWorkspace) -> PyResult<String> {
    let ws = workspace.lock();
    let loader = ws.repo_loader();
    let op = head_operation(loader)?;
    let index_store = loader.index_store();
    let index = pollster::block_on(index_store.get_index_at_op(&op, loader.store())).map_err(err)?;
    let Some(index) = index.downcast_ref::<DefaultReadonlyIndex>() else {
        return Err(err(format!(
            "Cannot get stats for indexes of type '{}'",
            index_store.name()
        )));
    };
    let stats = index.stats();
    let mut out = String::new();
    writeln!(out, "=== Commits ===").unwrap();
    writeln!(out, "Number of commits: {}", stats.num_commits).unwrap();
    writeln!(out, "Number of merges: {}", stats.num_merges).unwrap();
    writeln!(out, "Max generation number: {}", stats.max_generation_number).unwrap();
    writeln!(out, "Number of heads: {}", stats.num_heads).unwrap();
    writeln!(out, "Number of changes: {}", stats.num_changes).unwrap();
    writeln!(out, "Stats per level:").unwrap();
    for (i, level) in stats.commit_levels.iter().enumerate() {
        writeln!(out, "  Level {i}:").unwrap();
        writeln!(out, "    Number of commits: {}", level.num_commits).unwrap();
        writeln!(out, "    Name: {}", level.name).unwrap();
    }
    writeln!(out, "=== Changed paths ===").unwrap();
    match &stats.changed_path_commits_range {
        Some(range) => writeln!(out, "Indexed commits: {range:?}").unwrap(),
        None => writeln!(out, "Indexed commits: none").unwrap(),
    }
    writeln!(out, "Stats per level:").unwrap();
    for (i, level) in stats.changed_path_levels.iter().enumerate() {
        writeln!(out, "  Level {i}:").unwrap();
        writeln!(out, "    Number of commits: {}", level.num_commits).unwrap();
        writeln!(out, "    Number of changed paths: {}", level.num_changed_paths).unwrap();
        writeln!(out, "    Number of paths: {}", level.num_paths).unwrap();
        writeln!(out, "    Name: {}", level.name).unwrap();
    }
    Ok(out)
}

/// `jj debug reindex`: rebuild the index at the head operation. Returns
/// the number of commits indexed.
#[pyfunction]
pub fn debug_reindex(workspace: &PyWorkspace) -> PyResult<u32> {
    let ws = workspace.lock();
    let loader = ws.repo_loader();
    let op = head_operation(loader)?;
    let store = default_index_store(loader)?;
    store.reinit().map_err(err)?;
    let index =
        pollster::block_on(store.build_index_at_operation(&op, loader.store())).map_err(err)?;
    Ok(index.num_commits())
}

/// `jj debug index-changed-paths`: build the changed-path index for up to
/// `limit` commits. Returns the indexed range, formatted as jj does.
#[pyfunction]
pub fn debug_index_changed_paths(
    workspace: &PyWorkspace,
    repo: &PyReadonlyRepo,
    limit: u32,
) -> PyResult<Option<String>> {
    let ws = workspace.lock();
    let store = default_index_store(ws.repo_loader())?;
    let index = pollster::block_on(store.build_changed_path_index_at_operation(
        repo.inner.op_id(),
        repo.inner.store(),
        limit,
        |_| {},
    ))
    .map_err(err)?;
    // jj unwraps here; a library returns `None` when nothing is indexed.
    Ok(index.stats().changed_path_commits_range.map(|range| format!("{range:?}")))
}

/// `jj debug stacked-table`.
#[pyfunction]
pub fn debug_stacked_table(dir: &str, key_size: usize) -> PyResult<String> {
    let store = TableStore::load(PathBuf::from(dir), key_size);
    let table = store
        .get_head()
        .map_err(|e| err(format!("Failed to load stacked table: {e}")))?;
    let mut segments: Vec<_> = table.ancestor_segments().collect();
    segments.reverse();
    let total: usize = segments.iter().map(|t| t.segment_num_entries()).sum();
    let mut out = String::new();
    writeln!(out, "Number of entries: {total}").unwrap();
    writeln!(out, "Stats per level:").unwrap();
    for (i, table) in segments.iter().enumerate() {
        writeln!(out, "  Level {i}:").unwrap();
        writeln!(out, "    Number of entries: {}", table.segment_num_entries()).unwrap();
        writeln!(out, "    Name: {}", table.name()).unwrap();
    }
    Ok(out)
}

/// `jj debug init-simple`: a repo on the proof-of-concept simple backend.
#[pyfunction]
pub fn debug_init_simple(settings: &PyUserSettings, path: &str) -> PyResult<()> {
    pollster::block_on(jj_lib::workspace::Workspace::init_simple(
        &settings.0,
        std::path::Path::new(path),
    ))
    .map_err(err)?;
    Ok(())
}

/// `jj debug working-copy`.
#[pyfunction]
pub fn debug_working_copy(workspace: &PyWorkspace) -> PyResult<String> {
    let ws = workspace.lock();
    let wc = ws.working_copy();
    Ok(format!(
        "Type: {:?}\nCurrent operation: {:?}\nCurrent tree: {:?}\n",
        wc.name(),
        wc.operation_id(),
        wc.tree().map_err(err)?
    ))
}

/// `jj debug watchman <subcommand>`. Returns `(stdout, stderr, error)`:
/// jj prints part of `status` before contacting watchman, so a failure
/// keeps that output. `error` is `(message, exit code)`; jj reports a
/// failed query as an internal error, exit 255.
#[pyfunction]
pub fn debug_watchman(
    workspace: &PyWorkspace,
    settings: &PyUserSettings,
    subcommand: &str,
) -> PyResult<(String, String, Option<(String, i32)>)> {
    use jj_lib::fsmonitor::{FsmonitorSettings, WatchmanConfig};
    use jj_lib::local_working_copy::LockedLocalWorkingCopy;

    let mut out = String::new();
    let internal = |e: &dyn std::fmt::Display| Some((format!("Internal error: {e}"), 255));
    let not_local = || {
        Some(("Error: This command requires a standard local-disk working copy".to_owned(), 1))
    };
    let default_config = WatchmanConfig {
        register_trigger: false,
    };
    let mut ws = workspace.lock();

    if subcommand == "reset-clock" {
        let op_id = ws.working_copy().operation_id().clone();
        let mut locked = pollster::block_on(ws.start_working_copy_mutation()).map_err(err)?;
        let Some(local) = locked.locked_wc().downcast_mut::<LockedLocalWorkingCopy>() else {
            return Ok((out, String::new(), not_local()));
        };
        local.reset_watchman().map_err(err)?;
        pollster::block_on(locked.finish(op_id)).map_err(err)?;
        return Ok((out, "Reset Watchman clock.\n".to_owned(), None));
    }

    let config = if subcommand == "status" {
        match FsmonitorSettings::from_settings(&settings.0).map_err(err)? {
            FsmonitorSettings::Watchman(config) => {
                writeln!(out, "Watchman is enabled via `fsmonitor.backend`.").unwrap();
                writeln!(
                    out,
                    "Background snapshotting is {}. Use \
                     `fsmonitor.watchman.register-snapshot-trigger` to control it.",
                    if config.register_trigger { "enabled" } else { "disabled" }
                )
                .unwrap();
                config
            }
            FsmonitorSettings::None => {
                writeln!(
                    out,
                    r#"Watchman is disabled. Set `fsmonitor.backend="watchman"` to enable."#
                )
                .unwrap();
                writeln!(out, "Attempting to contact the `watchman` CLI regardless...").unwrap();
                default_config
            }
            other => {
                let message = format!(
                    "Error: This command does not support the currently enabled \
                     filesystem monitor: {other:?}."
                );
                return Ok((out, String::new(), Some((message, 1))));
            }
        }
    } else {
        default_config
    };
    let Some(wc) = ws.working_copy().downcast_ref::<LocalWorkingCopy>() else {
        return Ok((out, String::new(), not_local()));
    };
    let (clock, changed_files) = match pollster::block_on(wc.query_watchman(&config)) {
        Ok(result) => result,
        Err(e) => return Ok((out, String::new(), internal(&e))),
    };
    match subcommand {
        "status" => {
            writeln!(out, "The watchman server seems to be installed and working correctly.")
                .unwrap();
            let active = match pollster::block_on(wc.is_watchman_trigger_registered(&config)) {
                Ok(active) => active,
                Err(e) => return Ok((out, String::new(), internal(&e))),
            };
            writeln!(
                out,
                "Background snapshotting is currently {}.",
                if active { "active" } else { "inactive" }
            )
            .unwrap();
        }
        "query-clock" => writeln!(out, "Clock: {clock:?}").unwrap(),
        "query-changed-files" => writeln!(out, "Changed files: {changed_files:?}").unwrap(),
        _ => return Err(err(format!("unknown watchman subcommand: {subcommand}"))),
    }
    Ok((out, String::new(), None))
}

/// `jj debug local-working-copy`: the tracked file states as well.
#[pyfunction]
pub fn debug_local_working_copy(workspace: &PyWorkspace) -> PyResult<String> {
    let ws = workspace.lock();
    let wc = ws
        .working_copy()
        .downcast_ref::<LocalWorkingCopy>()
        .ok_or_else(|| err("This command requires a standard local-disk working copy"))?;
    let mut out = format!(
        "Current operation: {:?}\nCurrent tree: {:?}\n",
        wc.operation_id(),
        wc.tree().map_err(err)?
    );
    for (file, state) in wc.file_states().map_err(err)? {
        writeln!(
            out,
            "{:?} {:13?} {:10?} {:?} {:?}",
            state.file_type, state.size, state.mtime.0, state.materialized_conflict_data, file
        )
        .unwrap();
    }
    Ok(out)
}
