use std::sync::Arc;

use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::config::{ConfigNamePathBuf, StackedConfig};
use jj_lib::dsl_util::{AliasDeclarationParser, AliasesMap};
use jj_lib::fileset::FilesetAliasesMap;
use jj_lib::repo::Repo as _;
use jj_lib::revset::{
    self, ResolvedRevset, ResolvedRevsetExpression, RevsetAliasesMap, RevsetDiagnostics, RevsetExtensions,
    RevsetParseContext, RevsetStreamExt as _, RevsetWorkspaceContext, SymbolResolver,
};
use jj_lib::ui_path::RepoPathUiConverter;

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{map_revset_eval_err, map_revset_parse_err};
use crate::settings::PyUserSettings;

/// Reads a `[<table_name>]` config table (e.g. `revset-aliases`,
/// `fileset-aliases`) from every layer of `config`, in ascending
/// precedence order, and builds an `AliasesMap` from it, as `jj`'s
/// `load_aliases_map` (in the `cli` crate) does. A declaration that does
/// not load is skipped; `UserSettings.warnings` reports it, with jj's
/// wording, because `alias_warnings` runs when the settings are built.
pub(crate) fn load_aliases_map<P>(config: &StackedConfig, table_name: &str) -> AliasesMap<P, String>
where
    P: AliasDeclarationParser + Default,
    P::Error: std::fmt::Display,
{
    build_aliases_map(config, table_name, &mut Vec::new()).unwrap_or_else(|_| AliasesMap::new())
}

/// The declarations in `config`'s alias tables that do not load, as jj
/// words its warning for each. A table key that is not a table raises,
/// as it does in jj.
pub(crate) fn alias_warnings(config: &StackedConfig) -> PyResult<Vec<String>> {
    let config_err = crate::errors::ConfigError::new_err;
    let mut warnings = Vec::new();
    let _: RevsetAliasesMap =
        build_aliases_map(config, "revset-aliases", &mut warnings).map_err(config_err)?;
    let _: FilesetAliasesMap =
        build_aliases_map(config, "fileset-aliases", &mut warnings).map_err(config_err)?;
    Ok(warnings)
}

fn build_aliases_map<P>(
    config: &StackedConfig,
    table_name: &str,
    warnings: &mut Vec<String>,
) -> Result<AliasesMap<P, String>, String>
where
    P: AliasDeclarationParser + Default,
    P::Error: std::fmt::Display,
{
    let table_path = ConfigNamePathBuf::from_iter([table_name]);
    let mut aliases_map = AliasesMap::new();
    for layer in config.layers() {
        let table = match layer.look_up_table(&table_path) {
            Ok(Some(table)) => table,
            Ok(None) => continue,
            Err(item) => {
                return Err(format!(
                    "Invalid type or value for {table_name}: Expected a table, but is {}",
                    item.type_name()
                ));
            }
        };
        for (decl, item) in table.iter() {
            let definition = if let Some(t) = item.as_table_like() {
                t.get("definition").and_then(|i| i.as_str())
            } else {
                item.as_str()
            };
            let loaded = definition
                .ok_or_else(|| {
                    format!(
                        "Expected a string or a table with a `definition` string key, but is {}",
                        item.type_name()
                    )
                })
                .and_then(|v| aliases_map.insert(decl, v, None).map_err(|e: P::Error| e.to_string()));
            if let Err(error) = loaded {
                warnings.push(format!("Failed to load `{table_name}.{decl}`: {error}"));
            }
        }
    }
    Ok(aliases_map)
}

/// Parses and evaluates a jj revset expression (e.g. `"@"`, `"main"`,
/// `"ancestors(@) & ~immutable()"`) against `repo`, returning matching
/// commits in the revset's own (topological, children-before-parents) order.
///
/// `revset-aliases`/`fileset-aliases` from `settings`'s config are honored
/// (including the built-in `trunk()`/`immutable_heads()`/`mutable()`/etc.
/// from jj's bundled `revsets.toml`, if `settings` was constructed with
/// `load_config=True` -- see `PyUserSettings`). `@` and other
/// workspace-relative symbols resolve using the workspace `repo` was
/// loaded from.
pub fn evaluate_revset(
    repo: &PyReadonlyRepo,
    settings: &PyUserSettings,
    revision: &str,
) -> PyResult<Vec<PyCommit>> {
    let repo_ref = repo.inner.as_ref();
    let evaluated = evaluate_user_revset(
        repo_ref,
        &repo.workspace_root,
        &repo.workspace_name,
        settings,
        revision,
    )?;

    let store = repo.inner.store();
    let commits: Vec<jj_lib::commit::Commit> =
        pollster::block_on(evaluated.stream().commits(store).try_collect())
            .map_err(map_revset_eval_err)?;

    Ok(commits
        .into_iter()
        .map(|inner| PyCommit {
            inner,
            _repo: Some(repo.inner.clone()),
        })
        .collect())
}

/// `evaluate_revset()` against a transaction's in-progress repo, so a
/// query sees commits the transaction has already written. Returns bare
/// `CommitId`s: a `MutableRepo` is not an `Arc<ReadonlyRepo>`, so the
/// commits cannot carry a repo handle the way `PyCommit` expects.
pub fn evaluate_revset_mut(
    repo: &jj_lib::repo::MutableRepo,
    workspace_root: &std::path::Path,
    workspace_name: &jj_lib::ref_name::WorkspaceNameBuf,
    settings: &PyUserSettings,
    revision: &str,
) -> PyResult<Vec<crate::ids::PyCommitId>> {
    let evaluated = evaluate_user_revset(repo, workspace_root, workspace_name, settings, revision)?;
    let ids: Vec<jj_lib::backend::CommitId> =
        pollster::block_on(evaluated.stream().try_collect()).map_err(map_revset_eval_err)?;
    Ok(ids.into_iter().map(crate::ids::PyCommitId).collect())
}

/// Parses and symbol-resolves (but does not evaluate) a revset expression
/// against `repo` -- the `Arc<ResolvedRevsetExpression>` shared by
/// `evaluate_revset` and anything else (e.g. `absorb`) that needs to hand a
/// revset *domain* to a deeper `jj_lib` primitive rather than a concrete
/// list of commits. Generic over `&dyn Repo` (rather than `PyReadonlyRepo`
/// specifically) so it also works against a `MutableRepo` mid-transaction.
/// Parse a revset expression against the workspace-rooted converter and
/// the loaded alias tables, without resolving its symbols.
///
/// `resolve_revset` (evaluated) and `parse_revset` (unresolved, for
/// `IdPrefixContext::disambiguate_within`) share everything up to the
/// final call, so the context construction lives here once: a new alias
/// table upstream must not land in one and miss the other.
fn parse_user_revset(
    store: &jj_lib::store::Store,
    settings: &PyUserSettings,
    workspace_root: &std::path::Path,
    workspace_name: &jj_lib::ref_name::WorkspaceNameBuf,
    revision: &str,
) -> PyResult<Arc<revset::UserRevsetExpression>> {
    let path_converter = RepoPathUiConverter::Fs {
        cwd: workspace_root.to_path_buf(),
        base: workspace_root.to_path_buf(),
    };
    let workspace_ctx = RevsetWorkspaceContext {
        path_converter: &path_converter,
        workspace_name,
    };
    let aliases_map: RevsetAliasesMap = load_aliases_map(settings.0.config(), "revset-aliases");
    let fileset_aliases_map: FilesetAliasesMap =
        load_aliases_map(settings.0.config(), "fileset-aliases");
    let extensions = RevsetExtensions::new();
    let parse_context = RevsetParseContext {
        aliases_map: &aliases_map,
        local_variables: Default::default(),
        user_email: settings.0.user_email(),
        date_pattern_context: chrono::Local::now().into(),
        // `default_ignored_remote_name` in jj's cli_util.rs: a Git-backed
        // store hides `@git` from `remote_bookmarks()` and its kin.
        default_ignored_remote: jj_lib::git::get_git_backend(store)
            .is_ok()
            .then_some(jj_lib::git::REMOTE_NAME_FOR_LOCAL_GIT_REPO),
        fileset_aliases_map: &fileset_aliases_map,
        extensions: &extensions,
        workspace: Some(workspace_ctx),
    };

    let mut diagnostics = RevsetDiagnostics::new();
    revset::parse(&mut diagnostics, revision, &parse_context).map_err(map_revset_parse_err)
}

fn resolve_user_revset<'a>(
    repo: &'a dyn jj_lib::repo::Repo,
    workspace_root: &std::path::Path,
    workspace_name: &jj_lib::ref_name::WorkspaceNameBuf,
    settings: &PyUserSettings,
    revision: &str,
) -> PyResult<ResolvedRevset<'a>> {
    let expression =
        parse_user_revset(repo.store(), settings, workspace_root, workspace_name, revision)?;
    let extensions = RevsetExtensions::new();
    let symbol_resolver = SymbolResolver::new(repo, extensions.symbol_resolvers());
    expression
        .resolve_user_expression(repo, &symbol_resolver)
        .map_err(map_revset_eval_err)
}

/// Evaluates through `ResolvedRevset::evaluate`, which merges in the index
/// of every operation an `at_operation()` names. Without it, an operation
/// that is newer than `repo` or a sibling of it names commits `repo`'s own
/// index does not hold.
fn evaluate_user_revset(
    repo: &dyn jj_lib::repo::Repo,
    workspace_root: &std::path::Path,
    workspace_name: &jj_lib::ref_name::WorkspaceNameBuf,
    settings: &PyUserSettings,
    revision: &str,
) -> PyResult<Box<dyn revset::Revset>> {
    resolve_user_revset(repo, workspace_root, workspace_name, settings, revision)?
        .evaluate()
        .map_err(map_revset_eval_err)
}

/// The resolved expression alone, for callers that combine it with other
/// expressions. It is evaluated against `repo`'s index, so an
/// `at_operation()` here can only name an ancestor operation.
pub fn resolve_revset(
    repo: &dyn jj_lib::repo::Repo,
    workspace_root: &std::path::Path,
    workspace_name: &jj_lib::ref_name::WorkspaceNameBuf,
    settings: &PyUserSettings,
    revision: &str,
) -> PyResult<Arc<ResolvedRevsetExpression>> {
    Ok(resolve_user_revset(repo, workspace_root, workspace_name, settings, revision)?
        .into_inner()
        .0)
}

/// Parses a revset expression *without* resolving its symbols, which is
/// what `IdPrefixContext::disambiguate_within` wants -- it takes a
/// `UserRevsetExpression` and resolves it itself, against whichever repo
/// it is later populated with.
pub fn parse_revset(
    store: &jj_lib::store::Store,
    workspace_root: &std::path::Path,
    workspace_name: &jj_lib::ref_name::WorkspaceNameBuf,
    settings: &PyUserSettings,
    revision: &str,
) -> PyResult<Arc<revset::UserRevsetExpression>> {
    parse_user_revset(store, settings, workspace_root, workspace_name, revision)
}
