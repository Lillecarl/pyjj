use std::sync::Arc;

use futures::TryStreamExt as _;
use pyo3::prelude::*;

use jj_lib::config::{ConfigNamePathBuf, StackedConfig};
use jj_lib::dsl_util::{AliasDeclarationParser, AliasesMap};
use jj_lib::fileset::FilesetAliasesMap;
use jj_lib::repo::Repo as _;
use jj_lib::repo_path::RepoPathUiConverter;
use jj_lib::revset::{
    self, ResolvedRevsetExpression, RevsetAliasesMap, RevsetDiagnostics, RevsetExtensions,
    RevsetParseContext, RevsetStreamExt as _, RevsetWorkspaceContext, SymbolResolver,
};

use crate::commit::{PyCommit, PyReadonlyRepo};
use crate::errors::{map_revset_eval_err, map_revset_parse_err};
use crate::settings::PyUserSettings;

/// Reads a `[<table_name>]` config table (e.g. `revset-aliases`,
/// `fileset-aliases`) from every layer of `config`, in ascending
/// precedence order, and builds an `AliasesMap` from it -- the same thing
/// `jj`'s `load_aliases_map` (in the `cli` crate) does, reimplemented here
/// without the `Ui`-based warning printing (entries that fail to parse are
/// just skipped: a headless library has nowhere good to print a warning,
/// and a bad alias definition will surface as a normal parse error at the
/// point it's actually used, same as any other unresolvable symbol).
fn load_aliases_map<P>(config: &StackedConfig, table_name: &str) -> AliasesMap<P, String>
where
    P: AliasDeclarationParser + Default,
{
    let table_name = ConfigNamePathBuf::from_iter([table_name]);
    let mut aliases_map = AliasesMap::new();
    for layer in config.layers() {
        let Ok(Some(table)) = layer.look_up_table(&table_name) else {
            continue;
        };
        for (decl, item) in table.iter() {
            let definition = if let Some(t) = item.as_table_like() {
                t.get("definition").and_then(|i| i.as_str())
            } else {
                item.as_str()
            };
            if let Some(definition) = definition {
                let _ = aliases_map.insert(decl, definition, None);
            }
        }
    }
    aliases_map
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
    let resolved = resolve_revset(
        repo_ref,
        &repo.workspace_root,
        &repo.workspace_name,
        settings,
        revision,
    )?;

    let evaluated = resolved.evaluate(repo_ref).map_err(map_revset_eval_err)?;

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

/// Parses and symbol-resolves (but does not evaluate) a revset expression
/// against `repo` -- the `Arc<ResolvedRevsetExpression>` shared by
/// `evaluate_revset` and anything else (e.g. `absorb`) that needs to hand a
/// revset *domain* to a deeper `jj_lib` primitive rather than a concrete
/// list of commits. Generic over `&dyn Repo` (rather than `PyReadonlyRepo`
/// specifically) so it also works against a `MutableRepo` mid-transaction.
pub fn resolve_revset(
    repo: &dyn jj_lib::repo::Repo,
    workspace_root: &std::path::Path,
    workspace_name: &jj_lib::ref_name::WorkspaceNameBuf,
    settings: &PyUserSettings,
    revision: &str,
) -> PyResult<Arc<ResolvedRevsetExpression>> {
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
        default_ignored_remote: None,
        fileset_aliases_map: &fileset_aliases_map,
        extensions: &extensions,
        workspace: Some(workspace_ctx),
    };

    let mut diagnostics = RevsetDiagnostics::new();
    let expression =
        revset::parse(&mut diagnostics, revision, &parse_context).map_err(map_revset_parse_err)?;

    let symbol_resolver = SymbolResolver::new(repo, extensions.symbol_resolvers());
    expression
        .resolve_user_expression(repo, &symbol_resolver)
        .map_err(map_revset_eval_err)
}
