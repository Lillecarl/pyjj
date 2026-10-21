use std::collections::HashMap;
use std::io;

use pyo3::prelude::*;

use jj_lib::git::{
    self, GitFetch, GitFetchRefExpression, GitImportOptions, GitProgress, GitPushOptions,
    GitPushRefTargets, GitSidebandLineTerminator, GitSubprocessCallback,
};
use jj_lib::config::ConfigGetError;
use jj_lib::merge::Diff;
use jj_lib::settings::{RemoteSettings, RemoteSettingsMap};
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

/// `load_git_import_options` in jj's git_util.rs: `git.*` and
/// `remotes.<name>.auto-track-bookmarks`. A key `settings` did not load
/// falls back to jj's default.
fn import_options(settings: &PyUserSettings) -> PyResult<GitImportOptions> {
    let flag = |key: &'static str| match settings.0.get_bool(key) {
        Err(ConfigGetError::NotFound { .. }) => Ok(true),
        other => other.map_err(map_py_err),
    };
    let mut remote_auto_track_bookmarks = HashMap::new();
    for (name, remote) in remote_settings(settings)? {
        if let Some(text) = &remote.auto_track_bookmarks {
            let expr = remote_expression(&name, text, "auto-track-bookmarks")?;
            remote_auto_track_bookmarks.insert(name, expr.to_matcher());
        }
    }
    Ok(GitImportOptions {
        abandon_unreachable_commits: flag("git.abandon-unreachable-commits")?,
        record_synthetic_predecessors: flag("git.record-synthetic-predecessors")?,
        remote_auto_track_bookmarks,
    })
}

fn remote_settings(settings: &PyUserSettings) -> PyResult<RemoteSettingsMap> {
    RemoteSettings::table_from_settings(&settings.0).map_err(map_py_err)
}

/// `parse_remote_string_expression` in jj's revset_util.rs.
fn remote_expression(name: &RemoteName, text: &str, field: &str) -> PyResult<StringExpression> {
    jj_lib::revset::parse_string_expression(&mut jj_lib::revset::RevsetDiagnostics::new(), text)
        .map_err(|err| {
            crate::errors::JjError::new_err(format!(
                "Invalid `remotes.{}.{field}`: {}",
                name.as_symbol(),
                err.kind()
            ))
        })
}

/// Reflect changes made in the underlying (colocated) Git repo into the jj
/// view: new/moved/deleted Git refs become remote bookmarks/tags, reachable
/// commits become visible. Returns a summary dict.
pub fn import_refs(
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
) -> PyResult<PyGitImportStats> {
    let stats = pollster::block_on(git::import_refs(mut_repo, &import_options(settings)?))
        .map_err(map_git_import_err)?;
    Ok(PyGitImportStats::new(&stats, None))
}
/// `jj`'s colocated-repo HEAD update: point git's `HEAD` at the first
/// parent of `workspace_name`'s working-copy commit, which is what
/// `finish_transaction` does just before it exports refs. jj keeps HEAD
/// one step behind `@`, because `@` is the commit being written, not a
/// checked-out one. Does nothing when the workspace has no working-copy
/// commit in this transaction.
pub fn reset_head(
    mut_repo: &mut MutableRepo,
    workspace_name: &str,
    workspace_root: &std::path::Path,
) -> PyResult<()> {
    use jj_lib::ref_name::WorkspaceNameBuf;
    let name = WorkspaceNameBuf::from(workspace_name);
    let Some(id) = mut_repo.view().get_wc_commit_id(&name).cloned() else {
        return Ok(());
    };
    let commit = pollster::block_on(mut_repo.store().get_commit_async(&id))
        .map_err(crate::errors::map_backend_err)?;
    pollster::block_on(git::reset_head(mut_repo, name.as_ref(), workspace_root, &commit))
        .map_err(|err| crate::errors::JjError::new_err(err.to_string()))?;
    Ok(())
}


/// Reflect bookmark/tag changes made in the jj view into the underlying
/// (colocated) Git repo's refs. Returns a summary dict.
/// `export_refs` without the Python summary, for callers already inside
/// `py.detach()` that only need the side effect.
pub fn export_refs_only(mut_repo: &mut MutableRepo) -> PyResult<()> {
    git::export_refs(mut_repo).map_err(map_git_export_err)?;
    Ok(())
}

pub fn export_refs(mut_repo: &mut MutableRepo) -> PyResult<PyGitExportStats> {
    let stats = git::export_refs(mut_repo).map_err(map_git_export_err)?;
    let symbols = |failed: &[(jj_lib::ref_name::RemoteRefSymbolBuf, _)]| {
        failed.iter().map(|(symbol, _)| symbol.to_string()).collect()
    };
    Ok(PyGitExportStats {
        failed_bookmarks: symbols(&stats.failed_bookmarks),
        failed_tags: symbols(&stats.failed_tags),
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

/// Every configured Git remote, as `(name, fetch_url, push_url)`.
///
/// `jj git remote list` prints the URL beside each name, and says so
/// when fetch and push differ. A remote with an empty `[remote "..."]`
/// section is skipped, the way jj skips it.
pub fn remote_urls(store: &jj_lib::store::Store) -> PyResult<Vec<(String, String, String)>> {
    let git_repo = git::get_git_repo(store).map_err(map_py_err)?;
    let mut out = Vec::new();
    for name in git_repo.remote_names() {
        let Some(remote) = git_repo.try_find_remote(bstr::BStr::new(&name)) else {
            continue; // an empty [remote "<name>"] section
        };
        let remote = remote.map_err(|err| {
            crate::errors::JjError::new_err(format!(
                "Failed to load configured remote {name}: {err}"
            ))
        })?;
        let url = |direction| {
            remote
                .url(direction)
                .map(|url| url.to_bstring().to_string())
                .unwrap_or_default()
        };
        out.push((
            name.to_string(),
            url(gix::remote::Direction::Fetch),
            url(gix::remote::Direction::Push),
        ));
    }
    Ok(out)
}

/// Add a Git remote. Runs `git remote add` under the hood (via the Git
/// backend's on-disk repo), not just an in-memory record. `push_url` sets
/// a separate push URL.
pub fn add_remote(
    mut_repo: &mut MutableRepo,
    name: &str,
    url: &str,
    push_url: Option<&str>,
) -> PyResult<()> {
    git::add_remote(mut_repo, RemoteName::new(name), url, push_url).map_err(map_py_err)
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
    pollster::block_on(mut_repo.track_remote_bookmark(symbol)).map_err(map_py_err)
}

/// Stop tracking `{bookmark}@{remote}`.
pub fn untrack_remote_bookmark(mut_repo: &mut MutableRepo, remote: &str, bookmark: &str) {
    let symbol = RefName::new(bookmark).to_remote_symbol(RemoteName::new(remote));
    mut_repo.untrack_remote_bookmark(symbol);
}

/// `jj tag track` equivalent for one remote tag: a tracked remote tag
/// merges into the local tag of the same name on the next fetch.
pub fn track_remote_tag(
    mut_repo: &mut MutableRepo,
    remote: &str,
    tag: &str,
) -> PyResult<()> {
    let symbol = RefName::new(tag).to_remote_symbol(RemoteName::new(remote));
    pollster::block_on(mut_repo.track_remote_tag(symbol)).map_err(map_py_err)
}

/// `jj tag untrack` equivalent for one remote tag.
pub fn untrack_remote_tag(mut_repo: &mut MutableRepo, remote: &str, tag: &str) {
    let symbol = RefName::new(tag).to_remote_symbol(RemoteName::new(remote));
    mut_repo.untrack_remote_tag(symbol);
}

/// The refs one `jj git fetch` asks `remote` for.
///
/// jj builds two expressions per remote, one for bookmarks and one for
/// tags. The three cases are `--tracked`, a fetch that names branches
/// or tags, and a plain fetch.
///
/// A plain fetch reads the remote's own bookmark refspec out of the Git
/// config and asks for every tag. Naming anything asks for exactly what
/// was named, which is why `-b side` brings no tag with it.
///
/// A plain fetch honours `remotes.<name>.fetch-bookmarks` and
/// `fetch-tags` first, as jj does.
fn fetch_expressions(
    mut_repo: &MutableRepo,
    settings: &PyUserSettings,
    remote_name: &RemoteName,
    branches: Option<Vec<String>>,
    tags: Option<Vec<String>>,
    tracked: bool,
) -> PyResult<(StringExpression, StringExpression)> {
    if tracked {
        // Only what this repository already tracks, named exactly. A
        // remote bookmark nobody tracks is not asked for again.
        let view = mut_repo.view();
        let bookmark = StringExpression::union_all(
            view.local_remote_bookmarks(remote_name)
                .filter(|(_, targets)| targets.remote_ref.is_tracked())
                .map(|(name, _)| StringExpression::exact(name.as_str()))
                .collect(),
        );
        let tag = StringExpression::union_all(
            view.local_remote_tags(remote_name)
                .filter(|(_, targets)| targets.remote_ref.is_tracked())
                .map(|(name, _)| StringExpression::exact(name.as_str()))
                .collect(),
        );
        return Ok((bookmark, tag));
    }

    let is_specific = branches.is_some() || tags.is_some();
    let remote = remote_settings(settings)?.remove(remote_name);
    let configured = |text: Option<&String>, field: &str| {
        text.map(|text| remote_expression(remote_name, text, field)).transpose()
    };
    let bookmark = match branches {
        Some(patterns) => bookmark_expression(Some(patterns))?,
        None if is_specific => StringExpression::none(),
        None => if let Some(expr) =
            configured(remote.as_ref().and_then(|r| r.fetch_bookmarks.as_ref()), "fetch-bookmarks")?
        {
            expr
        } else {
            let git_repo = git::get_git_backend(mut_repo.store())
                .map_err(map_py_err)?
                .git_repo();
            // The second half is the refspecs jj cannot express, which
            // it warns about. There is no ui here, so they are dropped.
            let (_ignored, expr) =
                git::load_default_fetch_bookmarks(remote_name, &git_repo).map_err(map_py_err)?;
            expr
        },
    };
    let tag = match tags {
        Some(patterns) => bookmark_expression(Some(patterns))?,
        None if is_specific => StringExpression::none(),
        None => configured(remote.as_ref().and_then(|r| r.fetch_tags.as_ref()), "fetch-tags")?
            .unwrap_or_else(StringExpression::all),
    };
    Ok((bookmark, tag))
}

/// `jj git fetch` equivalent: runs `git fetch` (as a subprocess, so it
/// reuses the system's normal Git authentication — SSH agent, credential
/// helpers, etc.) against `remote`, then imports the fetched refs into
/// the view.
///
/// `branches` and `tags` are name patterns, `tracked` asks for only what
/// this repository already tracks; see `fetch_expressions` for what each
/// combination asks the remote for.
///
/// Returns the same summary dict shape as `git_import_refs()`.
pub fn fetch(
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    remote: &str,
    branches: Option<Vec<String>>,
    tags: Option<Vec<String>>,
    tracked: bool,
) -> PyResult<PyGitImportStats> {
    let remote_name = RemoteName::new(remote);
    let subprocess_options =
        jj_lib::git::GitSubprocessOptions::from_settings(&settings.0).map_err(map_py_err)?;
    let import_options = import_options(settings)?;

    let (bookmark, tag) =
        fetch_expressions(mut_repo, settings, remote_name, branches, tags, tracked)?;
    let expr = GitFetchRefExpression { bookmark, tag };
    let expanded = git::expand_fetch_refspecs(remote_name, expr).map_err(map_py_err)?;

    let mut git_fetch =
        GitFetch::new(mut_repo, subprocess_options, &import_options).map_err(map_py_err)?;
    let mut callback = SilentCallback;
    git_fetch
        .fetch(remote_name, expanded, &mut callback, None)
        .map_err(map_git_fetch_err)?;
    let stats = pollster::block_on(git_fetch.import_refs()).map_err(map_git_import_err)?;

    Ok(PyGitImportStats::new(&stats, None))
}

/// The bookmark patterns `jj git clone -b` accepts, as one expression.
///
/// jj documents the pattern as glob syntax with only `*` expanded. A
/// pattern with no `*` is an exact name, which is also what makes it
/// eligible to become the working-copy parent. jj's own parser accepts
/// `|` and `~` between patterns too; this takes them one an argument
/// instead, which is the shape the flag is repeated in.
pub fn bookmark_expression(patterns: Option<Vec<String>>) -> PyResult<StringExpression> {
    let Some(patterns) = patterns else {
        return Ok(StringExpression::all());
    };
    let mut parts = Vec::new();
    for pattern in patterns {
        let part = if pattern.contains('*') {
            jj_lib::str_util::StringPattern::glob(&pattern).map_err(|err| {
                crate::errors::JjError::new_err(format!("invalid branch pattern: {err}"))
            })?
        } else {
            jj_lib::str_util::StringPattern::exact(pattern)
        };
        parts.push(StringExpression::pattern(part));
    }
    Ok(StringExpression::union_all(parts))
}

/// What a Git import did: `git_import_refs`, `git_fetch` and
/// `git_fetch_all`. `default_branch` is set by `git_fetch_all` only.
#[pyclass(name = "GitImportStats", module = "pyjj_bindings", frozen, get_all)]
pub struct PyGitImportStats {
    pub abandoned_commits: usize,
    pub rewritten_commits: usize,
    pub changed_remote_bookmarks: usize,
    pub changed_remote_tags: usize,
    pub failed_ref_names: Vec<String>,
    /// The remote's default branch, as `git remote show` reports it.
    pub default_branch: Option<String>,
}

impl PyGitImportStats {
    fn new(stats: &git::GitImportStats, default_branch: Option<&RefNameBuf>) -> Self {
        Self {
            abandoned_commits: stats.abandoned_commits.len(),
            rewritten_commits: stats.rewritten_commit_ids.len(),
            changed_remote_bookmarks: stats.changed_remote_bookmarks.len(),
            changed_remote_tags: stats.changed_remote_tags.len(),
            failed_ref_names: stats.failed_ref_names.iter().map(|n| n.to_string()).collect(),
            default_branch: default_branch.map(|name| name.as_str().to_owned()),
        }
    }
}

/// What a Git export did: the refs jj could not write to the Git repo.
#[pyclass(name = "GitExportStats", module = "pyjj_bindings", frozen, get_all)]
pub struct PyGitExportStats {
    pub failed_bookmarks: Vec<String>,
    pub failed_tags: Vec<String>,
}

/// `fetch_all_inner`'s result: the stats, and the default branch as a
/// ref name, for `Workspace.clone_git()` to check out.
pub struct FetchAllResult {
    pub default_branch: Option<RefNameBuf>,
    pub stats: PyGitImportStats,
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
    bookmark: StringExpression,
    tag: StringExpression,
    depth: Option<u32>,
) -> PyResult<FetchAllResult> {
    let remote_name = RemoteName::new(remote);
    let subprocess_options =
        jj_lib::git::GitSubprocessOptions::from_settings(&settings.0).map_err(map_py_err)?;
    let import_options = import_options(settings)?;

    let expr = GitFetchRefExpression { bookmark, tag };
    let expanded = git::expand_fetch_refspecs(remote_name, expr).map_err(map_py_err)?;

    let depth = depth.and_then(std::num::NonZeroU32::new);

    let mut git_fetch =
        GitFetch::new(mut_repo, subprocess_options, &import_options).map_err(map_py_err)?;
    let mut callback = SilentCallback;
    git_fetch
        .fetch(remote_name, expanded, &mut callback, depth)
        .map_err(map_git_fetch_err)?;
    let default_branch = git_fetch
        .get_default_branch(remote_name)
        .map_err(map_git_fetch_err)?;
    let stats = pollster::block_on(git_fetch.import_refs()).map_err(map_git_import_err)?;

    Ok(FetchAllResult {
        stats: PyGitImportStats::new(&stats, default_branch.as_ref()),
        default_branch,
    })
}

/// `Transaction.git_fetch_all()`'s implementation -- see `fetch_all_inner`.
/// Returns the same stats shape as `fetch()`, plus `default_branch`
/// (`Optional[str]`).
pub fn fetch_all(
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    remote: &str,
) -> PyResult<PyGitImportStats> {
    let result = fetch_all_inner(
        mut_repo,
        settings,
        remote,
        StringExpression::all(),
        StringExpression::all(),
        None,
    )?;
    Ok(result.stats)
}

/// `jj git push`, with the caller deciding what to push.
///
/// `updates` is one entry a bookmark: `(name, before, after)`, where
/// `before` is the commit the remote is expected to hold and `after`
/// the one to put there. `None` on either side means the ref is absent
/// -- `before: None` creates it, `after: None` deletes it. Git rejects
/// the push when the remote does not hold `before`, which is how a
/// concurrent push is caught.
///
/// One call pushes every update together, because git does: a push is
/// one connection, and jj reports the whole batch's result at once.
///
/// `push_options` carries `jj git push -o`, the values git sends to the
/// receiving side. A remote that does not advertise push options
/// refuses the push outright.
///
/// The caller decides what belongs in `updates`. Which bookmarks jj
/// selects, and which selections it refuses, is `jj git push`'s own
/// logic and lives in pyjj-cli.
pub fn push_updates(
    mut_repo: &mut MutableRepo,
    settings: &PyUserSettings,
    remote: &str,
    updates: Vec<(String, Option<crate::ids::PyCommitId>, Option<crate::ids::PyCommitId>)>,
    push_options: Vec<String>,
) -> PyResult<Py<PyAny>> {
    let remote_name = RemoteName::new(remote);
    let targets = GitPushRefTargets {
        bookmarks: updates
            .into_iter()
            .map(|(name, before, after)| {
                (
                    RefNameBuf::from(name.as_str()),
                    Diff::new(before.map(|id| id.0), after.map(|id| id.0)),
                )
            })
            .collect(),
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
        &GitPushOptions {
            remote_push_options: push_options,
        },
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
