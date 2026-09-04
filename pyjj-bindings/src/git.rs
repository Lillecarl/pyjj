use std::collections::HashMap;
use std::io;

use pyo3::prelude::*;
use pyo3::types::PyDict;

use jj_lib::git::{
    self, GitFetch, GitFetchRefExpression, GitImportOptions, GitProgress, GitPushOptions,
    GitPushRefTargets, GitSidebandLineTerminator, GitSubprocessCallback,
};
use jj_lib::merge::Diff;
use jj_lib::ref_name::{RefName, RefNameBuf, RemoteName};
use jj_lib::repo::{MutableRepo, Repo as _};
use jj_lib::str_util::StringExpression;

use crate::errors::{
    map_git_export_err, map_git_fetch_err, map_git_import_err, map_git_push_err, map_py_err,
};
use crate::settings::PyUserSettings;

/// No-op callback: fetch/push run without progress reporting. A Python
/// callback hook isn't wired up yet.
struct SilentCallback;

impl GitSubprocessCallback for SilentCallback {
    fn needs_progress(&self) -> bool {
        false
    }

    fn progress(&mut self, _progress: &GitProgress) -> io::Result<()> {
        Ok(())
    }

    fn local_sideband(
        &mut self,
        _message: &[u8],
        _term: Option<GitSidebandLineTerminator>,
    ) -> io::Result<()> {
        Ok(())
    }

    fn remote_sideband(
        &mut self,
        _message: &[u8],
        _term: Option<GitSidebandLineTerminator>,
    ) -> io::Result<()> {
        Ok(())
    }
}

/// Matches jj's own built-in defaults (`lib/src/config/misc.toml`):
/// `git.abandon-unreachable-commits = true`,
/// `git.record-synthetic-predecessors = true`. No per-remote auto-track
/// patterns are configured — `jj_lib`'s config-driven equivalent
/// (`git.auto-local-bookmark` and friends) isn't wired up here yet.
fn default_import_options() -> GitImportOptions {
    GitImportOptions {
        abandon_unreachable_commits: true,
        record_synthetic_predecessors: true,
        remote_auto_track_bookmarks: HashMap::new(),
    }
}

/// Reflect changes made in the underlying (colocated) Git repo into the jj
/// view: new/moved/deleted Git refs become remote bookmarks/tags, reachable
/// commits become visible. Returns a summary dict.
pub fn import_refs(mut_repo: &mut MutableRepo) -> PyResult<Py<PyAny>> {
    let stats = pollster::block_on(git::import_refs(mut_repo, &default_import_options()))
        .map_err(map_git_import_err)?;
    Python::attach(|py| {
        let dict = PyDict::new(py);
        dict.set_item("abandoned_commits", stats.abandoned_commits.len())?;
        dict.set_item("rewritten_commits", stats.rewritten_commit_ids.len())?;
        dict.set_item(
            "changed_remote_bookmarks",
            stats.changed_remote_bookmarks.len(),
        )?;
        dict.set_item("changed_remote_tags", stats.changed_remote_tags.len())?;
        dict.set_item(
            "failed_ref_names",
            stats
                .failed_ref_names
                .iter()
                .map(|n| n.to_string())
                .collect::<Vec<_>>(),
        )?;
        Ok(dict.unbind().into_any())
    })
}
/// `jj`'s colocated-repo HEAD update: point git's `HEAD` at the first
/// parent of `workspace_name`'s working-copy commit, which is what
/// `finish_transaction` does just before it exports refs. jj keeps HEAD
/// one step behind `@`, because `@` is the commit being written, not a
/// checked-out one. Does nothing when the workspace has no working-copy
/// commit in this transaction.
pub fn reset_head(mut_repo: &mut MutableRepo, workspace_name: &str) -> PyResult<()> {
    use jj_lib::ref_name::WorkspaceNameBuf;
    let name = WorkspaceNameBuf::from(workspace_name);
    let Some(id) = mut_repo.view().get_wc_commit_id(&name).cloned() else {
        return Ok(());
    };
    let commit = pollster::block_on(mut_repo.store().get_commit_async(&id))
        .map_err(crate::errors::map_backend_err)?;
    pollster::block_on(git::reset_head(mut_repo, &commit))
        .map_err(|err| crate::errors::JjError::new_err(err.to_string()))?;
    Ok(())
}


/// Reflect bookmark/tag changes made in the jj view into the underlying
/// (colocated) Git repo's refs. Returns a summary dict.
pub fn export_refs(mut_repo: &mut MutableRepo) -> PyResult<Py<PyAny>> {
    let stats = git::export_refs(mut_repo).map_err(map_git_export_err)?;
    Python::attach(|py| {
        let dict = PyDict::new(py);
        dict.set_item(
            "failed_bookmarks",
            stats
                .failed_bookmarks
                .iter()
                .map(|(symbol, _)| symbol.to_string())
                .collect::<Vec<_>>(),
        )?;
        dict.set_item(
            "failed_tags",
            stats
                .failed_tags
                .iter()
                .map(|(symbol, _)| symbol.to_string())
                .collect::<Vec<_>>(),
        )?;
        Ok(dict.unbind().into_any())
    })
}

/// Names of all configured Git remotes.
pub fn list_remotes(store: &jj_lib::store::Store) -> PyResult<Vec<String>> {
    Ok(git::get_all_remote_names(store)
        .map_err(map_py_err)?
        .into_iter()
        .map(|name| name.as_str().to_string())
        .collect())
}

/// Add a Git remote. Runs `git remote add` under the hood (via the Git
/// backend's on-disk repo), not just an in-memory record.
pub fn add_remote(mut_repo: &mut MutableRepo, name: &str, url: &str) -> PyResult<()> {
    git::add_remote(
        mut_repo,
        RemoteName::new(name),
        url,
        None,
        gix::remote::fetch::Tags::default(),
    )
    .map_err(map_py_err)
}

/// Remove a Git remote.
pub fn remove_remote(mut_repo: &mut MutableRepo, name: &str) -> PyResult<()> {
    git::remove_remote(mut_repo, RemoteName::new(name)).map_err(map_py_err)
}

/// `jj git remote rename` equivalent: renames the remote in the underlying
/// Git repo's config and updates every remote-tracking bookmark/tag/Git ref
/// that referred to the old name to refer to the new one instead.
pub fn rename_remote(mut_repo: &mut MutableRepo, old_name: &str, new_name: &str) -> PyResult<()> {
    git::rename_remote(
        mut_repo,
        RemoteName::new(old_name),
        RemoteName::new(new_name),
    )
    .map_err(map_py_err)
}

/// `jj git remote set-url` equivalent: updates the remote's fetch URL
/// and/or push URL in the underlying Git repo's config. Passing `None` for
/// either leaves that URL unchanged (there's no way to unset just one via
/// this call, matching `jj_lib::git::set_remote_urls`'s own contract).
pub fn set_remote_urls(
    store: &jj_lib::store::Store,
    name: &str,
    url: Option<&str>,
    push_url: Option<&str>,
) -> PyResult<()> {
    git::set_remote_urls(store, RemoteName::new(name), url, push_url).map_err(map_py_err)
}

/// Start tracking `{bookmark}@{remote}`: merges its current target into the
/// local bookmark of the same name, and future `git_import_refs()`/
/// `git_fetch()` calls will keep merging updates in automatically.
pub fn track_remote_bookmark(
    mut_repo: &mut MutableRepo,
    remote: &str,
    bookmark: &str,
) -> PyResult<()> {
    let symbol = RefName::new(bookmark).to_remote_symbol(RemoteName::new(remote));
    mut_repo.track_remote_bookmark(symbol).map_err(map_py_err)
}

/// Stop tracking `{bookmark}@{remote}`.
pub fn untrack_remote_bookmark(mut_repo: &mut MutableRepo, remote: &str, bookmark: &str) {
    let symbol = RefName::new(bookmark).to_remote_symbol(RemoteName::new(remote));
    mut_repo.untrack_remote_bookmark(symbol);
}

/// `jj git fetch` equivalent: runs `git fetch` (as a subprocess, so it
/// reuses the system's normal Git authentication — SSH agent, credential
/// helpers, etc.) for the given bookmark names against `remote`, then
/// imports the fetched refs into the view. Tags are not fetched.
///
/// Returns the same summary dict shape as `git_import_refs()`.
pub fn fetch(
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    remote: &str,
    bookmark_names: Vec<String>,
) -> PyResult<Py<PyAny>> {
    let remote_name = RemoteName::new(remote);
    let subprocess_options =
        jj_lib::git::GitSubprocessOptions::from_settings(&settings.0).map_err(map_py_err)?;
    let import_options = default_import_options();

    let expr = GitFetchRefExpression {
        bookmark: StringExpression::union_all(
            bookmark_names.iter().map(StringExpression::exact).collect(),
        ),
        tag: StringExpression::none(),
    };
    let expanded = git::expand_fetch_refspecs(remote_name, expr).map_err(map_py_err)?;

    let mut git_fetch =
        GitFetch::new(mut_repo, subprocess_options, &import_options).map_err(map_py_err)?;
    let mut callback = SilentCallback;
    git_fetch
        .fetch(remote_name, expanded, &mut callback, None, None)
        .map_err(map_git_fetch_err)?;
    let stats = pollster::block_on(git_fetch.import_refs()).map_err(map_git_import_err)?;

    Python::attach(|py| {
        let dict = PyDict::new(py);
        dict.set_item("abandoned_commits", stats.abandoned_commits.len())?;
        dict.set_item("rewritten_commits", stats.rewritten_commit_ids.len())?;
        dict.set_item(
            "changed_remote_bookmarks",
            stats.changed_remote_bookmarks.len(),
        )?;
        dict.set_item("changed_remote_tags", stats.changed_remote_tags.len())?;
        dict.set_item(
            "failed_ref_names",
            stats
                .failed_ref_names
                .iter()
                .map(|n| n.to_string())
                .collect::<Vec<_>>(),
        )?;
        Ok(dict.unbind().into_any())
    })
}

/// Plain-Rust result of `fetch_all_inner` -- used both to build
/// `fetch_all()`'s Python-facing stats dict and, in `workspace.rs`'s
/// `Workspace.clone_git()`, to decide what to check out without round-
/// tripping through a `Py<PyAny>` dict.
pub struct FetchAllResult {
    pub default_branch: Option<RefNameBuf>,
    pub abandoned_commits: usize,
    pub rewritten_commits: usize,
    pub changed_remote_bookmarks: usize,
    pub changed_remote_tags: usize,
    pub failed_ref_names: Vec<String>,
}

/// `jj git clone`'s fetch step: fetches *all* branches and tags from
/// `remote` (as a subprocess) and imports them, additionally querying the
/// remote's default branch name (`git remote show`, same as `GitFetch::
/// get_default_branch`) -- unlike `fetch()`, which only fetches the named
/// bookmarks and fetches no tags.
pub fn fetch_all_inner(
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    remote: &str,
) -> PyResult<FetchAllResult> {
    let remote_name = RemoteName::new(remote);
    let subprocess_options =
        jj_lib::git::GitSubprocessOptions::from_settings(&settings.0).map_err(map_py_err)?;
    let import_options = default_import_options();

    let expr = GitFetchRefExpression {
        bookmark: StringExpression::all(),
        tag: StringExpression::all(),
    };
    let expanded = git::expand_fetch_refspecs(remote_name, expr).map_err(map_py_err)?;

    let mut git_fetch =
        GitFetch::new(mut_repo, subprocess_options, &import_options).map_err(map_py_err)?;
    let mut callback = SilentCallback;
    git_fetch
        .fetch(remote_name, expanded, &mut callback, None, None)
        .map_err(map_git_fetch_err)?;
    let default_branch = git_fetch
        .get_default_branch(remote_name)
        .map_err(map_git_fetch_err)?;
    let stats = pollster::block_on(git_fetch.import_refs()).map_err(map_git_import_err)?;

    Ok(FetchAllResult {
        default_branch,
        abandoned_commits: stats.abandoned_commits.len(),
        rewritten_commits: stats.rewritten_commit_ids.len(),
        changed_remote_bookmarks: stats.changed_remote_bookmarks.len(),
        changed_remote_tags: stats.changed_remote_tags.len(),
        failed_ref_names: stats
            .failed_ref_names
            .iter()
            .map(|n| n.to_string())
            .collect(),
    })
}

/// `Transaction.git_fetch_all()`'s implementation -- see `fetch_all_inner`.
/// Returns the same stats shape as `fetch()`, plus `default_branch`
/// (`Optional[str]`).
pub fn fetch_all(
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    remote: &str,
) -> PyResult<Py<PyAny>> {
    let result = fetch_all_inner(mut_repo, settings, remote)?;
    Python::attach(|py| {
        let dict = PyDict::new(py);
        dict.set_item("abandoned_commits", result.abandoned_commits)?;
        dict.set_item("rewritten_commits", result.rewritten_commits)?;
        dict.set_item("changed_remote_bookmarks", result.changed_remote_bookmarks)?;
        dict.set_item("changed_remote_tags", result.changed_remote_tags)?;
        dict.set_item("failed_ref_names", result.failed_ref_names)?;
        dict.set_item(
            "default_branch",
            result
                .default_branch
                .as_ref()
                .map(|n| n.as_str().to_string()),
        )?;
        Ok(dict.unbind().into_any())
    })
}

/// `jj git push -b <bookmark>` equivalent: pushes the local bookmark's
/// current target to `remote` (as a subprocess `git push`), expecting the
/// remote to currently be at whatever `{bookmark}@{remote}` is tracked as
/// (use `track_remote_bookmark()` first if it isn't tracked yet — otherwise
/// this expects the remote ref to not exist, and Git will reject a
/// non-fast-forward push).
///
/// The local bookmark must resolve to exactly one commit (not absent, not
/// conflicted).
pub fn push_bookmark(
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    remote: &str,
    bookmark: &str,
) -> PyResult<Py<PyAny>> {
    let remote_name = RemoteName::new(remote);
    let name = RefName::new(bookmark);

    let local_target = mut_repo.get_local_bookmark(name);
    if local_target.is_absent() {
        return Err(crate::errors::JjError::new_err(format!(
            "bookmark `{bookmark}` doesn't exist locally, nothing to push"
        )));
    }
    let after = local_target.as_normal().cloned().ok_or_else(|| {
        crate::errors::JjError::new_err(format!(
            "bookmark `{bookmark}` is conflicted; resolve before pushing"
        ))
    })?;
    let before = mut_repo
        .view()
        .get_remote_bookmark(name.to_remote_symbol(remote_name))
        .tracked_target()
        .as_normal()
        .cloned();

    if before.as_ref() == Some(&after) {
        return Python::attach(|py| -> PyResult<Py<PyAny>> {
            let dict = PyDict::new(py);
            dict.set_item("pushed", Vec::<String>::new())?;
            dict.set_item("rejected", Vec::<(String, Option<String>)>::new())?;
            dict.set_item("remote_rejected", Vec::<(String, Option<String>)>::new())?;
            Ok(dict.unbind().into_any())
        });
    }

    let targets = GitPushRefTargets {
        bookmarks: vec![(RefNameBuf::from(bookmark), Diff::new(before, Some(after)))],
        tags: vec![],
    };

    let subprocess_options =
        jj_lib::git::GitSubprocessOptions::from_settings(&settings.0).map_err(map_py_err)?;
    let mut callback = SilentCallback;
    let stats = git::push_refs(
        mut_repo,
        subprocess_options,
        remote_name,
        &targets,
        &mut callback,
        &GitPushOptions::default(),
    )
    .map_err(map_git_push_err)?;

    Python::attach(|py| {
        let dict = PyDict::new(py);
        dict.set_item(
            "pushed",
            stats
                .pushed
                .iter()
                .map(|n| n.as_str().to_string())
                .collect::<Vec<_>>(),
        )?;
        dict.set_item(
            "rejected",
            stats
                .rejected
                .iter()
                .map(|(n, reason)| (n.as_str().to_string(), reason.clone()))
                .collect::<Vec<_>>(),
        )?;
        dict.set_item(
            "remote_rejected",
            stats
                .remote_rejected
                .iter()
                .map(|(n, reason)| (n.as_str().to_string(), reason.clone()))
                .collect::<Vec<_>>(),
        )?;
        Ok(dict.unbind().into_any())
    })
}
