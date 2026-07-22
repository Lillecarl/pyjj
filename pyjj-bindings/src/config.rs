//! Loads jj's real config layers (system/user config files, `revset-aliases`
//! defaults, environment variable overrides) so callers see the same
//! effective config as the `jj` CLI would in the same environment.
//!
//! This mirrors `ConfigEnv` in jj's `cli` crate (which isn't reusable as a
//! library dependency -- it's tied to `cli`'s own `Ui`/`CommandError`
//! types), reimplemented directly against `jj_lib::config`'s public
//! `StackedConfig`/`ConfigLayer` API plus the same `etcetera`/`whoami`
//! crates `cli` uses for platform config-dir/hostname discovery, so the
//! file locations and precedence order match exactly.
//!
//! **Deliberately out of scope**: repo-level (`.jj/repo/`) and
//! workspace-level (`.jj/<workspace>/`) config. Real jj stores those behind
//! an ID-indirection scheme (`SecureConfig`, in `jj_lib::secure_config`)
//! specifically so that cloning a repo can't silently make its config (e.g.
//! merge-tool commands, aliases) take effect without the user opting in --
//! reimplementing that trust boundary casually would be a real security
//! regression, not just a missing feature. System/user config and env vars
//! (which are always under the *local user's* control) carry no such risk.

use std::env;
use std::path::{Path, PathBuf};

use etcetera::BaseStrategy as _;
use jj_lib::config::{ConfigLayer, ConfigLoadError, ConfigSource, StackedConfig};

const OP_HOSTNAME: &str = "operation.hostname";
const OP_USERNAME: &str = "operation.username";

/// jj's built-in `revset-aliases` (`trunk()`, `immutable_heads()`,
/// `mutable()`, `visible()`, `hidden()`, etc.) and revset-driven command
/// defaults. These live in the `jj` CLI's bundled config, not `jj_lib`'s
/// own (much smaller) defaults -- without them, revset expressions that
/// real `jj` users take for granted (like `mutable()`) don't resolve at
/// all. Vendored into `vendor/revsets.toml` (copied from jj's
/// `cli/src/config/revsets.toml` -- see that file's own header comment
/// about keeping `docs/revsets.md` in sync when updating it) rather than
/// reached via a path into a jj monorepo checkout, since this crate has no
/// such checkout as a sibling. Re-sync it whenever the `jj-lib` version
/// pin in `Cargo.toml` is bumped to a release with revset-alias changes.
fn revsets_default_layer() -> ConfigLayer {
    ConfigLayer::parse(
        ConfigSource::Default,
        include_str!("../vendor/revsets.toml"),
    )
    .expect("bundled vendor/revsets.toml should parse")
}

/// Values jj derives from the environment that config files should be free
/// to override (`operation.hostname`/`operation.username`, from
/// `whoami`, falling back to `$USER` for the username on platforms where
/// `whoami` can't determine it).
fn env_base_layer() -> ConfigLayer {
    let mut layer = ConfigLayer::empty(ConfigSource::EnvBase);
    if let Ok(value) = whoami::hostname() {
        let _ = layer.set_value(OP_HOSTNAME, value);
    }
    if let Ok(value) = whoami::username() {
        let _ = layer.set_value(OP_USERNAME, value);
    } else if let Ok(value) = env::var("USER") {
        let _ = layer.set_value(OP_USERNAME, value);
    }
    layer
}

/// Environment variables that override config values (highest-precedence
/// layer short of actual command-line arguments, which don't apply to a
/// library). Mirrors `cli`'s `env_overrides_layer`, minus `JJ_EDITOR`/
/// `JJ_PAGER` (no interactive UI here to configure).
fn env_overrides_layer() -> ConfigLayer {
    let mut layer = ConfigLayer::empty(ConfigSource::EnvOverrides);
    if let Ok(value) = env::var("JJ_USER") {
        let _ = layer.set_value("user.name", value);
    }
    if let Ok(value) = env::var("JJ_EMAIL") {
        let _ = layer.set_value("user.email", value);
    }
    if let Ok(value) = env::var("JJ_TIMESTAMP") {
        let _ = layer.set_value("debug.commit-timestamp", value);
    }
    if let Ok(Ok(value)) = env::var("JJ_RANDOMNESS_SEED").map(|s| s.parse::<i64>()) {
        let _ = layer.set_value("debug.randomness-seed", value);
    }
    if let Ok(value) = env::var("JJ_OP_TIMESTAMP") {
        let _ = layer.set_value("debug.operation-timestamp", value);
    }
    if let Ok(value) = env::var("JJ_OP_HOSTNAME") {
        let _ = layer.set_value(OP_HOSTNAME, value);
    }
    if let Ok(value) = env::var("JJ_OP_USERNAME") {
        let _ = layer.set_value(OP_USERNAME, value);
    }
    layer
}

/// System-wide config paths: `/etc/jj/config.toml` and `/etc/jj/conf.d/` on
/// Unix (jj has no defined system config location on Windows). Suppressed
/// entirely when `JJ_CONFIG` is set, matching `jj`'s own behavior -- an
/// explicit `JJ_CONFIG` means "use only this," not "use this in addition
/// to the usual places."
fn system_config_paths() -> Vec<PathBuf> {
    if env::var_os("JJ_CONFIG").is_some() {
        return Vec::new();
    }
    if cfg!(unix) {
        let etc = Path::new("/etc");
        vec![etc.join("jj/config.toml"), etc.join("jj/conf.d")]
    } else {
        Vec::new()
    }
}

/// User config paths, in ascending precedence order (later entries win on
/// conflicting keys): `~/.jjconfig.toml` (legacy, included if it exists,
/// or if there's no platform config dir to fall back to),
/// `<platform config dir>/jj/config.toml`, then
/// `<platform config dir>/jj/conf.d/` if it exists. All of this is skipped
/// in favor of `JJ_CONFIG`'s paths (`:`-separated on Unix, `;` on Windows)
/// if that env var is set.
fn user_config_paths() -> Vec<PathBuf> {
    if let Some(paths) = env::var_os("JJ_CONFIG") {
        return env::split_paths(&paths)
            .filter(|p| !p.as_os_str().is_empty())
            .collect();
    }

    let base_strategy = etcetera::choose_base_strategy().ok();
    let user_config_dir = base_strategy.map(|s| s.config_dir());
    let home_dir = etcetera::home_dir()
        .ok()
        .map(|d| dunce::canonicalize(&d).unwrap_or(d));

    let home_config_path = home_dir.map(|mut home| {
        home.push(".jjconfig.toml");
        home
    });
    let platform_config_path = user_config_dir.clone().map(|mut dir| {
        dir.push("jj");
        dir.push("config.toml");
        dir
    });
    let platform_config_dir = user_config_dir.map(|mut dir| {
        dir.push("jj");
        dir.push("conf.d");
        dir
    });

    let mut paths = Vec::new();
    if let Some(path) = &home_config_path
        && (path.exists() || platform_config_path.is_none())
    {
        paths.push(path.clone());
    }
    if let Some(path) = platform_config_path {
        paths.push(path);
    }
    if let Some(path) = platform_config_dir
        && path.exists()
    {
        paths.push(path);
    }
    paths
}

fn load_layers_at(
    config: &mut StackedConfig,
    source: ConfigSource,
    paths: &[PathBuf],
) -> Result<(), ConfigLoadError> {
    for path in paths {
        if !path.exists() {
            continue;
        }
        if path.is_dir() {
            config.load_dir(source, path)?;
        } else {
            config.load_file(source, path)?;
        }
    }
    Ok(())
}

/// Builds the full effective config `jj` itself would use in this
/// environment: jj_lib's own built-in defaults, the bundled `revsets.toml`
/// aliases, system config, hostname/username, user config, then env var
/// overrides -- everything except repo/workspace config (see module docs)
/// and command-line `--config` (not applicable to a library).
pub fn load_default_config() -> Result<StackedConfig, ConfigLoadError> {
    let mut config = StackedConfig::with_defaults();
    config.add_layer(revsets_default_layer());
    config.add_layer(env_base_layer());
    load_layers_at(&mut config, ConfigSource::System, &system_config_paths())?;
    load_layers_at(&mut config, ConfigSource::User, &user_config_paths())?;
    config.add_layer(env_overrides_layer());
    Ok(config)
}
