use std::sync::Arc;
use std::sync::Mutex;

use pyo3::prelude::*;
use pyo3::types::PyDict;

use jj_lib::commit::Commit;
use jj_lib::file_util;
use jj_lib::ref_name::{RemoteName, WorkspaceNameBuf};
use jj_lib::repo::{MutableRepo, ReadonlyRepo, Repo as _, StoreFactories};
use jj_lib::repo_path::RepoPathBuf;
use jj_lib::rewrite::merge_commit_trees;
use jj_lib::transaction::Transaction as JjTransaction;
use jj_lib::workspace::{Workspace, default_working_copy_factories, default_working_copy_factory};
use jj_lib::workspace_store::{SimpleWorkspaceStore, WorkspaceStore as _};

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{
    JjError, map_backend_err, map_checkout_err, map_repo_load_err, map_transaction_err,
    map_working_copy_err, map_workspace_init_err, map_workspace_load_err,
};
use crate::ids::PyCommitId;
use crate::settings::PyUserSettings;

/// The top-level entry point: a jj workspace (repo + working copy).
///
/// Wrapped in a `Mutex` (rather than a bare `Workspace`) so this class can
/// be a normal `Send + Sync` pyclass instead of `unsendable` -- jj_lib's
/// `Workspace` is `Send` but not `Sync` (it holds a `Box<dyn WorkingCopy>`,
/// and that trait doesn't declare `Sync`), and PyO3 requires ordinary
/// pyclasses to be both, since a Python object can legitimately be handed
/// to another thread across separate calls (e.g. by `asyncio.to_thread`).
/// The `Mutex` supplies the missing `Sync` -- and reflects reality anyway,
/// since a jj workspace's on-disk state is exclusive-access by nature (its
/// own lock files enforce the same thing). Methods that do real I/O also
/// use `Python::detach` (PyO3's GIL-release, formerly `allow_threads`)
/// around the locked section, so an `asyncio.to_thread()`-wrapped caller
/// genuinely frees the event loop for the duration -- see `AGENTS.md`'s
/// async section.
#[pyclass(name = "Workspace")]
pub struct PyWorkspace {
    pub(crate) inner: Mutex<Workspace>,
}

pub(crate) fn wrap_repo(ws: &Workspace, repo: Arc<ReadonlyRepo>) -> PyReadonlyRepo {
    PyReadonlyRepo {
        inner: repo,
        workspace_root: ws.workspace_root().to_path_buf(),
        workspace_name: ws.workspace_name().to_owned(),
    }
}

impl PyWorkspace {
    fn add_workspace_inner(
        inner: &Workspace,
        settings: &PyUserSettings,
        destination_path: String,
        name: Option<String>,
        revision_ids: Option<Vec<PyCommitId>>,
    ) -> PyResult<(Self, PyReadonlyRepo)> {
        let dest_path = std::path::Path::new(&destination_path);
        let workspace_name = match name {
            Some(n) => WorkspaceNameBuf::from(n.as_str()),
            None => {
                let file_name = dest_path.file_name().ok_or_else(|| {
                    JjError::new_err(
                        "destination path has no file name to derive a workspace name from",
                    )
                })?;
                let name_str = file_name
                    .to_str()
                    .ok_or_else(|| JjError::new_err("destination path is not valid UTF-8"))?;
                WorkspaceNameBuf::from(name_str)
            }
        };
        if workspace_name.as_str().is_empty() {
            return Err(JjError::new_err("workspace name cannot be empty"));
        }

        let repo =
            pollster::block_on(inner.repo_loader().load_at_head()).map_err(map_repo_load_err)?;
        if repo.view().get_wc_commit_id(&workspace_name).is_some() {
            return Err(JjError::new_err(format!(
                "workspace named `{}` already exists",
                workspace_name.as_str()
            )));
        }

        if !dest_path.exists() {
            std::fs::create_dir(dest_path)
                .map_err(|err| JjError::new_err(format!("{destination_path}: {err}")))?;
        } else if !file_util::is_empty_dir(dest_path).map_err(map_backend_err)? {
            return Err(JjError::new_err(
                "destination path exists and is not an empty directory",
            ));
        }

        let working_copy_factory = default_working_copy_factory();
        let repo_path = inner.repo_path().to_path_buf();
        let (new_ws, repo) = pollster::block_on(Workspace::init_workspace_with_existing_repo(
            dest_path,
            &repo_path,
            &repo,
            working_copy_factory.as_ref(),
            workspace_name.clone(),
        ))
        .map_err(map_workspace_init_err)?;

        let index = repo.readonly_index();
        let view = repo.view();
        let mut mut_repo = MutableRepo::new(repo.clone(), index, view);

        let parents: Vec<Commit> = match revision_ids {
            Some(ids) if !ids.is_empty() => ids
                .into_iter()
                .map(|id| {
                    pollster::block_on(mut_repo.store().get_commit_async(&id.0))
                        .map_err(map_backend_err)
                })
                .collect::<PyResult<_>>()?,
            _ => match repo.view().get_wc_commit_id(inner.workspace_name()) {
                Some(old_wc_id) => {
                    let old_wc = pollster::block_on(mut_repo.store().get_commit_async(old_wc_id))
                        .map_err(map_backend_err)?;
                    pollster::block_on(old_wc.parents()).map_err(map_backend_err)?
                }
                None => vec![mut_repo.store().root_commit()],
            },
        };
        let tree =
            pollster::block_on(merge_commit_trees(&mut_repo, &parents)).map_err(map_backend_err)?;
        let parent_ids = parents.iter().map(|c| c.id().clone()).collect();
        let new_wc_commit = pollster::block_on(mut_repo.new_commit(parent_ids, tree).write())
            .map_err(map_backend_err)?;
        pollster::block_on(mut_repo.edit(workspace_name.clone(), &new_wc_commit))
            .map_err(|err| JjError::new_err(err.to_string()))?;
        // `edit()` may abandon the placeholder (root-pointing) wc commit
        // `init_workspace_with_existing_repo` created for this workspace
        // name, which is a rewrite -- must be rebased away (a no-op here,
        // since nothing has children yet) before `Transaction::commit`,
        // which asserts no pending rewrites remain (same requirement
        // `checkout::snapshot` has).
        pollster::block_on(mut_repo.rebase_descendants()).map_err(map_transaction_err)?;

        let tx = JjTransaction::new(mut_repo, &settings.0);
        let new_repo = pollster::block_on(tx.commit(format!(
            "create initial working-copy commit in workspace {}",
            workspace_name.as_str()
        )))
        .map_err(map_transaction_err)?;

        let py_repo = wrap_repo(&new_ws, new_repo);
        Ok((
            Self {
                inner: Mutex::new(new_ws),
            },
            py_repo,
        ))
    }
}

#[pymethods]
impl PyWorkspace {
    /// Initialize a new jj workspace with an internal git backend at `path`.
    #[staticmethod]
    fn init_internal_git(
        settings: &PyUserSettings,
        workspace_path: String,
    ) -> PyResult<(Self, PyReadonlyRepo)> {
        let path = std::path::Path::new(&workspace_path);
        let (ws, repo) = pollster::block_on(Workspace::init_internal_git(&settings.0, path))
            .map_err(map_workspace_init_err)?;
        let py_repo = wrap_repo(&ws, repo);
        Ok((
            Self {
                inner: Mutex::new(ws),
            },
            py_repo,
        ))
    }

    /// Initialize a new jj workspace with a colocated git repo at `path`.
    #[staticmethod]
    fn init_colocated_git(
        settings: &PyUserSettings,
        workspace_path: String,
    ) -> PyResult<(Self, PyReadonlyRepo)> {
        let path = std::path::Path::new(&workspace_path);
        let (ws, repo) = pollster::block_on(Workspace::init_colocated_git(&settings.0, path))
        .map_err(map_workspace_init_err)?;
        let py_repo = wrap_repo(&ws, repo);
        Ok((
            Self {
                inner: Mutex::new(ws),
            },
            py_repo,
        ))
    }

    /// `jj git clone <url> <destination>` equivalent: initializes a new
    /// workspace at `destination_path`, adds `remote_name` (`"origin"` by
    /// default) pointing at `url`, fetches every branch and tag, and --
    /// if the remote reports a default branch -- tracks it as a local
    /// bookmark and checks it out as the initial working-copy commit
    /// (like `git clone`'s own default checkout behavior). If the remote
    /// has no discoverable default branch, the workspace is left with an
    /// empty working-copy commit on the root, same as a normal `init_*`.
    ///
    /// `colocate=True` (the default, matching real `jj git clone`) creates
    /// a `.git` dir alongside `.jj`, so regular Git tools also work
    /// directly in the resulting directory. `destination_path` must
    /// already exist as an empty directory, or not exist yet (it will be
    /// created) -- unlike the CLI, there's no URL-based destination
    /// auto-detection here.
    ///
    /// `branches` restricts what is fetched and picks the working-copy
    /// parent: the first pattern that names one branch exactly and
    /// exists on the remote wins, and the remote's default branch is
    /// the fallback. `depth` makes a shallow clone. `fetch_tags` is
    /// `"all"`, `"included"` or `"none"`; a clone defaults to all,
    /// the way git does.
    #[staticmethod]
    #[pyo3(signature = (settings, url, destination_path, remote_name=None, colocate=true,
                        branches=None, depth=None, fetch_tags=None))]
    fn clone_git(
        py: Python<'_>,
        settings: &PyUserSettings,
        url: String,
        destination_path: String,
        remote_name: Option<String>,
        colocate: bool,
        branches: Option<Vec<String>>,
        depth: Option<u32>,
        fetch_tags: Option<String>,
    ) -> PyResult<(Self, PyReadonlyRepo)> {
        py.detach(move || {
            let remote_name = remote_name.unwrap_or_else(|| "origin".to_string());
            let path = std::path::Path::new(&destination_path);
            if !path.exists() {
                std::fs::create_dir_all(path)
                    .map_err(|err| JjError::new_err(format!("{destination_path}: {err}")))?;
            } else if !file_util::is_empty_dir(path).map_err(map_backend_err)? {
                return Err(JjError::new_err(
                    "destination path exists and is not an empty directory",
                ));
            }

            let (_initial_ws, repo) = if colocate {
                pollster::block_on(Workspace::init_colocated_git(&settings.0, path))
            } else {
                pollster::block_on(Workspace::init_internal_git(&settings.0, path))
            }
            .map_err(map_workspace_init_err)?;

            // Add the remote.
            let index = repo.readonly_index();
            let view = repo.view();
            let mut mut_repo = MutableRepo::new(repo.clone(), index, view);
            crate::git::add_remote(&mut mut_repo, &remote_name, &url)?;
            let tx = JjTransaction::new(mut_repo, &settings.0);
            let repo = pollster::block_on(tx.commit(format!("add git remote {remote_name}")))
                .map_err(map_transaction_err)?;

            // The Git backend's remote config is cached for the lifetime of a
            // `Workspace`/`Store` object (see AGENTS.md's Git section) -- a
            // freshly-opened one is needed before the newly-added remote is
            // actually usable for fetching, same as `cli`'s own `git clone`
            // does (`configure_remote`'s "Reload workspace..." comment).
            let op_id = repo.operation().id().clone();
            let store_factories = StoreFactories::default();
            let working_copy_factories = default_working_copy_factories();
            let mut new_ws =
                Workspace::load(&settings.0, path, &store_factories, &working_copy_factories)
                    .map_err(map_workspace_load_err)?;
            let op = pollster::block_on(new_ws.repo_loader().load_operation(&op_id))
                .map_err(map_repo_load_err)?;
            let repo =
                pollster::block_on(new_ws.repo_loader().load_at(&op)).map_err(map_repo_load_err)?;

            // Fetch everything, and see if the remote told us a default branch.
            let index = repo.readonly_index();
            let view = repo.view();
            let mut mut_repo = MutableRepo::new(repo.clone(), index, view);
            let bookmark = crate::git::bookmark_expression(branches.clone())?;
            // A clone fetches every tag by default, the way git does.
            // Naming branches narrows the whole clone, though, so jj
            // stops fetching tags implicitly too.
            let effective_tags = match (&fetch_tags, &branches) {
                (Some(mode), _) => mode.clone(),
                (None, Some(_)) => "none".to_string(),
                (None, None) => "all".to_string(),
            };
            let fetch_result = crate::git::fetch_all_inner(
                &mut mut_repo,
                settings,
                &remote_name,
                bookmark,
                // A clone asks for no tag refspec at all and lets
                // `--fetch-tags` decide, which is how git itself fetches
                // tags on a clone. Naming them in the refspec would
                // fetch them whatever `--fetch-tags` said.
                jj_lib::str_util::StringExpression::none(),
                depth,
                Some(effective_tags.as_str()),
            )?;

            // Which branch the working copy starts on. `-b` names it: the
            // first pattern that is an exact name and exists on the remote
            // wins. Otherwise it is the branch the remote calls default.
            let present = |name: &str| {
                let symbol = jj_lib::ref_name::RefName::new(name)
                    .to_remote_symbol(RemoteName::new(&remote_name));
                mut_repo.get_remote_bookmark(symbol).target.as_normal().cloned()
            };
            let mut working: Option<String> = None;
            for pattern in branches.iter().flatten() {
                if pattern.contains('*') {
                    continue;
                }
                if present(pattern).is_some() {
                    working = Some(pattern.clone());
                    break;
                }
            }
            let default_name = fetch_result
                .default_branch
                .as_ref()
                .map(|name| name.as_str().to_string())
                .filter(|name| present(name).is_some());
            if working.is_none() {
                working = default_name.clone();
            }
            // jj creates the local bookmark only when the working branch
            // is the remote's own default, the way git clone does.
            let default_branch_commit: Option<Commit> = match &working {
                Some(name) => match present(name) {
                    Some(commit_id) => {
                        if Some(name) == default_name.as_ref() {
                            let symbol = jj_lib::ref_name::RefName::new(name.as_str())
                                .to_remote_symbol(RemoteName::new(&remote_name));
                            mut_repo
                                .track_remote_bookmark(symbol)
                                .map_err(|err| JjError::new_err(err.to_string()))?;
                        }
                        Some(
                            pollster::block_on(mut_repo.store().get_commit_async(&commit_id))
                                .map_err(map_backend_err)?,
                        )
                    }
                    None => None,
                },
                None => None,
            };
            // A colocated clone has to leave the git side consistent, the
            // way jj's own transaction finish does: the tracked bookmarks
            // it just created must exist as git refs too.
            if colocate {
                crate::git::export_refs_only(&mut mut_repo)?;
            }
            let tx = JjTransaction::new(mut_repo, &settings.0);
            let repo = pollster::block_on(tx.commit("fetch from git remote into empty repo"))
                .map_err(map_transaction_err)?;

            let Some(commit) = default_branch_commit else {
                let py_repo = wrap_repo(&new_ws, repo);
                return Ok((
                    Self {
                        inner: Mutex::new(new_ws),
                    },
                    py_repo,
                ));
            };

            let index = repo.readonly_index();
            let view = repo.view();
            let mut mut_repo = MutableRepo::new(repo.clone(), index, view);
            // `check_out` (not `edit`) -- creates a fresh, empty child commit
            // on top of the branch and moves the working copy there, same as
            // `jj new <branch>` / real `jj git clone`'s own `tx.check_out()`.
            // Editing straight onto the branch's own commit would let working-
            // copy edits silently move the bookmark itself.
            let wc_commit =
                pollster::block_on(mut_repo.check_out(new_ws.workspace_name().to_owned(), &commit))
                    .map_err(|err| JjError::new_err(err.to_string()))?;
            pollster::block_on(mut_repo.rebase_descendants()).map_err(map_transaction_err)?;
            if colocate {
                let name = new_ws.workspace_name().to_owned();
                crate::git::reset_head(&mut mut_repo, name.as_str())?;
                crate::git::export_refs_only(&mut mut_repo)?;
            }
            let tx = JjTransaction::new(mut_repo, &settings.0);
            let repo = pollster::block_on(tx.commit(format!(
                "check out git remote's branch: {}",
                fetch_result.default_branch.as_ref().unwrap().as_str()
            )))
            .map_err(map_transaction_err)?;

            let operation_id = repo.operation().id().clone();
            pollster::block_on(new_ws.check_out(operation_id, None, &wc_commit))
                .map_err(map_checkout_err)?;

            let py_repo = wrap_repo(&new_ws, repo);
            Ok((
                Self {
                    inner: Mutex::new(new_ws),
                },
                py_repo,
            ))
        })
    }

    /// Load an existing jj workspace from `workspace_path`.
    #[staticmethod]
    fn load(settings: &PyUserSettings, workspace_path: String) -> PyResult<Self> {
        let path = std::path::Path::new(&workspace_path);
        let store_factories = StoreFactories::default();
        let working_copy_factories = default_working_copy_factories();
        let ws = Workspace::load(&settings.0, path, &store_factories, &working_copy_factories)
            .map_err(map_workspace_load_err)?;
        Ok(Self {
            inner: Mutex::new(ws),
        })
    }

    /// The filesystem path to the workspace root.
    #[getter]
    fn workspace_root(&self) -> String {
        self.inner
            .lock()
            .unwrap()
            .workspace_root()
            .display()
            .to_string()
    }

    /// The name of this workspace, as seen in `view()`'s keys.
    #[getter]
    fn workspace_name(&self) -> String {
        self.inner
            .lock()
            .unwrap()
            .workspace_name()
            .as_str()
            .to_string()
    }

    /// The recorded filesystem path of the *named* workspace (any
    /// workspace sharing this repo, not just `self`), relative to `self`'s
    /// `repo_path` (`.jj/repo`) -- `None` if the workspace store has no
    /// record of it (already forgotten, or created before `workspace_store`
    /// existed).
    fn workspace_path(&self, name: &str) -> PyResult<Option<String>> {
        let inner = self.inner.lock().unwrap();
        let workspace_store = SimpleWorkspaceStore::load(inner.repo_path())
            .map_err(|err| JjError::new_err(err.to_string()))?;
        let workspace_name = WorkspaceNameBuf::from(name);
        let path = workspace_store
            .get_workspace_path(workspace_name.as_ref())
            .map_err(|err| JjError::new_err(err.to_string()))?;
        Ok(path.map(|p| p.display().to_string()))
    }

    /// The filesystem path to the repo (.jj/repo).
    #[getter]
    fn repo_path(&self) -> String {
        self.inner.lock().unwrap().repo_path().display().to_string()
    }

    /// Load the repo at the current operation (head).
    fn load_at_head(&self, py: Python<'_>) -> PyResult<PyReadonlyRepo> {
        py.detach(|| {
            let inner = self.inner.lock().unwrap();
            let repo: Arc<ReadonlyRepo> = pollster::block_on(inner.repo_loader().load_at_head())
                .map_err(map_repo_load_err)?;
            Ok(wrap_repo(&inner, repo))
        })
    }

    /// Snapshot the on-disk working copy into the working-copy commit's
    /// tree, committing that as a new operation. Returns
    /// `(new_repo, stats_dict)`. See `pyjj_bindings.checkout` module docs.
    #[pyo3(signature = (settings, args=None))]
    fn snapshot(
        &self,
        py: Python<'_>,
        settings: &PyUserSettings,
        args: Option<String>,
    ) -> PyResult<(PyReadonlyRepo, Py<PyAny>)> {
        py.detach(move || {
            let mut inner = self.inner.lock().unwrap();
            crate::checkout::snapshot(&mut inner, settings, args)
        })
    }

    /// `jj file untrack <paths>`: drop `paths` from the working-copy
    /// commit's tree, leaving the files on disk. Returns
    /// `(new_repo, added_back)`. When `added_back` is non-empty the paths
    /// were not ignored and NOTHING was written -- see
    /// `pyjj_bindings.checkout::untrack_paths`'s docs for why the check
    /// cannot happen before the write.
    fn untrack_paths(
        &self,
        py: Python<'_>,
        settings: &PyUserSettings,
        paths: Vec<String>,
    ) -> PyResult<(PyReadonlyRepo, Vec<String>)> {
        py.detach(move || {
            let mut inner = self.inner.lock().unwrap();
            crate::checkout::untrack_paths(&mut inner, settings, paths)
        })
    }

    /// Write `commit`'s tree out to the working-copy files and record
    /// `repo`'s operation as current. Returns a stats dict.
    fn check_out(
        &self,
        py: Python<'_>,
        repo: &PyReadonlyRepo,
        commit: &PyCommit,
    ) -> PyResult<Py<PyAny>> {
        py.detach(move || {
            let mut inner = self.inner.lock().unwrap();
            crate::checkout::check_out(&mut inner, repo, commit)
        })
    }

    /// Re-syncs the working copy's tracked-file-state bookkeeping to
    /// `commit`'s tree *without writing any files* -- see
    /// `pyjj_bindings.checkout::reset`'s docs. Use `check_out()` instead
    /// unless you specifically know the on-disk files already match
    /// `commit` (e.g. after an external tool updated them directly).
    fn reset(&self, py: Python<'_>, repo: &PyReadonlyRepo, commit: &PyCommit) -> PyResult<()> {
        py.detach(move || {
            let mut inner = self.inner.lock().unwrap();
            crate::checkout::reset(&mut inner, repo, commit)
        })
    }

    /// `jj op abandon <operation>` equivalent -- see
    /// `pyjj_bindings.oplog::op_abandon`'s docs for the full semantics
    /// (including the `"root..head"` range syntax). Edits the operation
    /// log directly rather than creating a new operation, so there's no
    /// `Transaction`/`commit()` step -- reload (`load_at_head()`) to see
    /// the effect.
    fn op_abandon(
        &self,
        py: Python<'_>,
        operation: &str,
    ) -> PyResult<crate::oplog::PyOpAbandonStats> {
        py.detach(move || {
            let mut inner = self.inner.lock().unwrap();
            crate::oplog::op_abandon(&mut inner, operation)
        })
    }

    /// `jj workspace update-stale` equivalent: if this workspace's on-disk
    /// state refers to an operation that's no longer current (e.g. another
    /// process advanced the repo, or `repo` is `self.load_at_head()`'s
    /// fresh result), resets the working copy to `repo`'s current
    /// working-copy commit. Pass a freshly-loaded `repo` (not one that
    /// might itself be stale).
    ///
    /// Returns `None` if the working copy wasn't actually stale (nothing
    /// done); otherwise a stats dict shaped like `check_out()`'s.
    ///
    /// Unlike the CLI's `workspace update-stale`, this does **not**
    /// attempt to snapshot and preserve any uncommitted local edits still
    /// sitting in the stale working copy before resetting -- if that
    /// matters, snapshot against the *old* operation yourself first (e.g.
    /// via a `Workspace` loaded at the stale op) before calling this,
    /// since it will otherwise simply overwrite them with `repo`'s tree.
    fn update_stale(&self, py: Python<'_>, repo: &PyReadonlyRepo) -> PyResult<Option<Py<PyAny>>> {
        py.detach(move || {
            let mut inner = self.inner.lock().unwrap();
            let wc_commit_id = repo
                .inner
                .view()
                .get_wc_commit_id(inner.workspace_name())
                .ok_or_else(|| {
                    JjError::new_err("workspace has no working-copy commit in this repo")
                })?;
            let desired_commit =
                pollster::block_on(repo.inner.store().get_commit_async(wc_commit_id))
                    .map_err(map_backend_err)?;

            let mut locked_ws = pollster::block_on(inner.start_working_copy_mutation())
                .map_err(map_working_copy_err)?;
            let freshness =
                pollster::block_on(jj_lib::working_copy::WorkingCopyFreshness::check_stale(
                    locked_ws.locked_wc(),
                    &desired_commit,
                    &repo.inner,
                ))
                .map_err(|err| JjError::new_err(err.to_string()))?;

            use jj_lib::working_copy::WorkingCopyFreshness;
            match freshness {
                WorkingCopyFreshness::Fresh | WorkingCopyFreshness::Updated(_) => {
                    drop(locked_ws);
                    Ok(None)
                }
                WorkingCopyFreshness::WorkingCopyStale | WorkingCopyFreshness::SiblingOperation => {
                    let stats =
                        pollster::block_on(locked_ws.locked_wc().check_out(&desired_commit))
                            .map_err(map_checkout_err)?;
                    let operation_id = repo.inner.operation().id().clone();
                    pollster::block_on(locked_ws.finish(operation_id))
                        .map_err(map_working_copy_err)?;
                    Python::attach(|py| -> PyResult<Option<Py<PyAny>>> {
                        let dict = PyDict::new(py);
                        dict.set_item("updated_files", stats.updated_files)?;
                        dict.set_item("added_files", stats.added_files)?;
                        dict.set_item("removed_files", stats.removed_files)?;
                        dict.set_item("skipped_files", stats.skipped_files)?;
                        Ok(Some(dict.unbind().into_any()))
                    })
                }
            }
        })
    }

    /// The current sparse patterns: repo-relative path strings, each
    /// naming a directory prefix whose files are present in the working
    /// copy. A single empty string (`[""]`) means "the whole repo" -- the
    /// default, unrestricted state. `jj sparse list` equivalent.
    fn sparse_patterns(&self) -> PyResult<Vec<String>> {
        let inner = self.inner.lock().unwrap();
        let patterns = inner
            .working_copy()
            .sparse_patterns()
            .map_err(map_working_copy_err)?;
        Ok(patterns
            .iter()
            .map(|p| p.as_internal_file_string().to_string())
            .collect())
    }

    /// Replaces the sparse patterns wholesale and updates the on-disk
    /// working copy to match (adding files that newly match, removing
    /// files that no longer do) -- `jj sparse set --clear --add ...`
    /// equivalent (pass `[""]` for "everything", matching `jj sparse
    /// reset`). Doesn't touch the repo's view or create a new jj
    /// operation, since sparse patterns are purely workspace-local state.
    /// Returns a stats dict shaped like `check_out()`'s.
    fn set_sparse_patterns(&self, py: Python<'_>, patterns: Vec<String>) -> PyResult<Py<PyAny>> {
        let repo_paths: Vec<RepoPathBuf> = patterns
            .iter()
            .map(|p| {
                RepoPathBuf::from_internal_string(p)
                    .map_err(|err| JjError::new_err(err.to_string()))
            })
            .collect::<PyResult<_>>()?;

        py.detach(move || {
            let mut inner = self.inner.lock().unwrap();
            let mut locked_ws = pollster::block_on(inner.start_working_copy_mutation())
                .map_err(map_working_copy_err)?;
            let stats = pollster::block_on(locked_ws.locked_wc().set_sparse_patterns(repo_paths))
                .map_err(map_checkout_err)?;
            let operation_id = locked_ws.locked_wc().old_operation_id().clone();
            pollster::block_on(locked_ws.finish(operation_id)).map_err(map_working_copy_err)?;

            Python::attach(|py| -> PyResult<Py<PyAny>> {
                let dict = PyDict::new(py);
                dict.set_item("updated_files", stats.updated_files)?;
                dict.set_item("added_files", stats.added_files)?;
                dict.set_item("removed_files", stats.removed_files)?;
                dict.set_item("skipped_files", stats.skipped_files)?;
                Ok(dict.unbind().into_any())
            })
        })
    }

    /// `jj workspace add <destination>` equivalent: creates a brand-new
    /// workspace (its own working-copy directory, independently checked
    /// out) backed by the *same* repo storage as `self`. `name` defaults to
    /// `destination`'s basename. `revision_ids`, if given, become the new
    /// workspace's initial working-copy commit's parents (like `jj new
    /// r1 r2 ...`); otherwise it defaults to the parent(s) of `self`'s own
    /// current working-copy commit (or the root commit, if `self` has none)
    /// -- same default `jj workspace add` uses.
    ///
    /// Returns the new `(Workspace, ReadonlyRepo)` pair -- `self`'s own repo
    /// object is unaffected by this call (call `load_at_head()` again on it
    /// to see the new workspace show up in `view()`).
    #[pyo3(signature = (settings, destination_path, name=None, revision_ids=None))]
    fn add_workspace(
        &self,
        py: Python<'_>,
        settings: &PyUserSettings,
        destination_path: String,
        name: Option<String>,
        revision_ids: Option<Vec<PyCommitId>>,
    ) -> PyResult<(Self, PyReadonlyRepo)> {
        py.detach(move || {
            let inner = self.inner.lock().unwrap();
            Self::add_workspace_inner(&inner, settings, destination_path, name, revision_ids)
        })
    }

    /// `jj workspace forget [names...]` equivalent: stops tracking the
    /// named workspaces' working-copy commits in the repo (bundled into a
    /// single operation, so undoing it restores all of them at once). Does
    /// **not** touch anything on disk in the forgotten workspaces'
    /// directories -- they can be deleted before or after this call.
    fn forget_workspaces(
        &self,
        py: Python<'_>,
        settings: &PyUserSettings,
        names: Vec<String>,
    ) -> PyResult<PyReadonlyRepo> {
        py.detach(move || {
            let inner = self.inner.lock().unwrap();
            if names.is_empty() {
                return Err(JjError::new_err(
                    "forget_workspaces requires at least one name",
                ));
            }
            let names: Vec<WorkspaceNameBuf> = names
                .iter()
                .map(|n| WorkspaceNameBuf::from(n.as_str()))
                .collect();

            let repo = pollster::block_on(inner.repo_loader().load_at_head())
                .map_err(map_repo_load_err)?;
            for name in &names {
                if repo.view().get_wc_commit_id(name).is_none() {
                    return Err(JjError::new_err(format!(
                        "no such workspace: `{}`",
                        name.as_str()
                    )));
                }
            }

            let workspace_store = SimpleWorkspaceStore::load(inner.repo_path())
                .map_err(|err| JjError::new_err(err.to_string()))?;

            let index = repo.readonly_index();
            let view = repo.view();
            let mut mut_repo = MutableRepo::new(repo.clone(), index, view);
            for name in &names {
                pollster::block_on(mut_repo.remove_wc_commit(name))
                    .map_err(|err| JjError::new_err(err.to_string()))?;
            }
            let name_refs: Vec<&jj_lib::ref_name::WorkspaceName> =
                names.iter().map(|n| n.as_ref()).collect();
            workspace_store
                .forget(&name_refs)
                .map_err(|err| JjError::new_err(err.to_string()))?;
            // remove_wc_commit() may abandon a forgotten workspace's discardable
            // wc commit, which is a rewrite that must be rebased away (a no-op
            // if it has no descendants) before Transaction::commit.
            pollster::block_on(mut_repo.rebase_descendants()).map_err(map_transaction_err)?;

            let description = if let [name] = names.as_slice() {
                format!("forget workspace {}", name.as_str())
            } else {
                format!(
                    "forget workspaces {}",
                    names
                        .iter()
                        .map(|n| n.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                )
            };
            let tx = JjTransaction::new(mut_repo, &settings.0);
            let new_repo =
                pollster::block_on(tx.commit(description)).map_err(map_transaction_err)?;
            Ok(wrap_repo(&inner, new_repo))
        })
    }

    /// `jj workspace rename <new_name>` equivalent: renames *this*
    /// workspace (the one `self` represents) in both the repo's view and
    /// the on-disk working-copy state -- a no-op returning the current
    /// head repo if `new_name` already matches.
    fn rename_workspace(
        &self,
        py: Python<'_>,
        settings: &PyUserSettings,
        new_name: String,
    ) -> PyResult<PyReadonlyRepo> {
        py.detach(move || {
            let mut inner = self.inner.lock().unwrap();
            let new_name = WorkspaceNameBuf::from(new_name.as_str());
            if new_name.as_str().is_empty() {
                return Err(JjError::new_err("new workspace name cannot be empty"));
            }
            let old_name = inner.workspace_name().to_owned();

            let repo = pollster::block_on(inner.repo_loader().load_at_head())
                .map_err(map_repo_load_err)?;
            if new_name == old_name {
                return Ok(wrap_repo(&inner, repo));
            }
            if repo.view().get_wc_commit_id(&old_name).is_none() {
                return Err(JjError::new_err(format!(
                    "the current workspace `{}` is not tracked in the repo",
                    old_name.as_str()
                )));
            }

            let workspace_store = SimpleWorkspaceStore::load(inner.repo_path())
                .map_err(|err| JjError::new_err(err.to_string()))?;

            let index = repo.readonly_index();
            let view = repo.view();
            let mut mut_repo = MutableRepo::new(repo.clone(), index, view);
            mut_repo
                .rename_workspace(&old_name, new_name.clone())
                .map_err(|err| JjError::new_err(err.to_string()))?;
            workspace_store
                .rename(&old_name, &new_name)
                .map_err(|err| JjError::new_err(err.to_string()))?;

            let mut locked_ws = pollster::block_on(inner.start_working_copy_mutation())
                .map_err(map_working_copy_err)?;
            locked_ws.locked_wc().rename_workspace(new_name.clone());

            let description = format!(
                "Renamed workspace '{}' to '{}'",
                old_name.as_str(),
                new_name.as_str()
            );
            let tx = JjTransaction::new(mut_repo, &settings.0);
            let new_repo =
                pollster::block_on(tx.commit(description)).map_err(map_transaction_err)?;

            pollster::block_on(locked_ws.finish(new_repo.operation().id().clone()))
                .map_err(map_working_copy_err)?;

            Ok(wrap_repo(&inner, new_repo))
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "Workspace({})",
            self.inner.lock().unwrap().workspace_root().display()
        )
    }
}
