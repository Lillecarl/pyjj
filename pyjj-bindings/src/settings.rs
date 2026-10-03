use pyo3::prelude::*;

use jj_lib::config::{ConfigLayer, ConfigSource};
use jj_lib::settings::UserSettings;

use crate::ids::PySignature;

/// One layer of the stacked config, as `UserSettings.config_layers()`
/// returns it. `entries` maps dotted keys (`"user.name"`) to values in
/// TOML syntax (`"\"Jane\""`), the way `jj config list -T` renders them.
#[pyclass(name = "ConfigLayer", frozen, get_all)]
pub struct PyConfigLayer {
    source: String,
    path: Option<String>,
    entries: std::collections::HashMap<String, String>,
}

/// Flatten one layer's TOML document to dotted keys. Tables recurse;
/// anything else (values, arrays, arrays of tables) renders whole at
/// its own key, since dotted syntax cannot name inside them. Values
/// render decor-free: `to_string()` would otherwise leak the whitespace
/// (or comments) sitting between the key and the value in the source.
fn flatten_layer(
    table: &toml_edit::Table,
    prefix: String,
    out: &mut std::collections::HashMap<String, String>,
) {
    for (key, item) in table.iter() {
        let dotted = if prefix.is_empty() {
            key.to_string()
        } else if key
            .chars()
            .all(|c| c.is_alphanumeric() || c == '_' || c == '-')
        {
            format!("{prefix}.{key}")
        } else {
            format!("{prefix}.{key:?}")
        };
        match item {
            toml_edit::Item::Table(table) => flatten_layer(table, dotted, out),
            toml_edit::Item::Value(value) => {
                let mut bare = value.clone();
                *bare.decor_mut() = Default::default();
                out.insert(dotted, bare.to_string());
            }
            _ => {
                out.insert(dotted, item.to_string().trim_start().to_string());
            }
        }
    }
}

/// Formats a config failure the way the `jj` CLI prints it, minus the
/// `Config error: ` prefix and help footer (the CLI owns those): the top
/// message, then the source chain -- inline when it is one link,
/// numbered when it is several.
fn error_chain_body(top: &dyn std::error::Error) -> String {
    let mut body = top.to_string();
    let mut chain: Vec<String> = Vec::new();
    let mut source = top.source();
    while let Some(error) = source {
        chain.push(error.to_string());
        source = error.source();
    }
    match chain.len() {
        0 => {}
        1 => {
            body.push_str("\nCaused by: ");
            body.push_str(&chain[0]);
        }
        _ => {
            body.push_str("\nCaused by:");
            for (index, link) in chain.iter().enumerate() {
                body.push_str(&format!("\n{}: {link}", index + 1));
            }
        }
    }
    body
}

/// One `--config NAME=VALUE` as a `CommandArg` layer.
///
/// Splits on the first `=`, so values may contain more of them. The
/// value parses as TOML, except a value starting with anything but `"`,
/// `'`, `[` or `{` falls back to a bare string when TOML parsing fails
/// (`--config user.name=Foo`, not `--config user.name="Foo"`).
fn parse_config_pair(text: &str) -> Result<ConfigLayer, String> {
    let (name, value) = text
        .split_once('=')
        .ok_or_else(|| "--config must be specified as NAME=VALUE".to_string())?;
    let name: jj_lib::config::ConfigNamePathBuf =
        name.parse().map_err(|err: toml_edit::TomlError| {
            format!("--config name cannot be parsed\nCaused by: {err}")
        })?;
    let strict = matches!(value.as_bytes().first(), Some(b'"' | b'\'' | b'[' | b'{'));
    let toml_value = match value.parse::<toml_edit::Value>() {
        Ok(value) => value,
        Err(err) if strict => {
            return Err(format!("--config value cannot be parsed\nCaused by: {err}"));
        }
        Err(_) => toml_edit::Value::from(value.to_string()),
    };
    let mut layer = ConfigLayer::empty(ConfigSource::CommandArg);
    layer
        .set_value(name, toml_value)
        .map_err(|err| error_chain_body(&err))?;
    Ok(layer)
}

/// User configuration loaded from jj config files.
#[pyclass(name = "UserSettings", frozen)]
pub struct PyUserSettings(pub(crate) UserSettings);

#[pymethods]
impl PyUserSettings {
    /// Creates settings from jj's real config, the same way the `jj` CLI
    /// would see it in this environment: built-in defaults, `revset-aliases`
    /// (`trunk()`, `mutable()`, etc.), system config (`/etc/jj/config.toml`
    /// on Unix), hostname/username, user config (`~/.jjconfig.toml` /
    /// platform config dir), then `JJ_USER`/`JJ_EMAIL`/etc. env var
    /// overrides -- everything except repo/workspace config (which arrive
    /// through `for_repo`) and command-line `--config`/`--config-file`
    /// (which arrive through `with_command_args`).
    ///
    /// Pass `load_config=False` to skip all of that and get only jj_lib's
    /// own built-in defaults (empty user name/email, no revset aliases) --
    /// useful for hermetic tests that shouldn't depend on the machine's
    /// real jj config.
    ///
    /// Repo and workspace config need a repository to belong to, so they
    /// arrive through `for_repo` instead.
    #[new]
    #[pyo3(signature = (load_config=true))]
    fn new(load_config: bool) -> PyResult<Self> {
        let config = if load_config {
            crate::config::load_default_config().map_err(crate::errors::map_py_err)?
        } else {
            jj_lib::config::StackedConfig::with_defaults()
        };
        let user_settings = UserSettings::from_config(config).map_err(crate::errors::map_py_err)?;
        Ok(Self(user_settings))
    }

    /// The same config the `jj` CLI would see *inside this repository*:
    /// everything the constructor loads, plus the repo and workspace
    /// layers jj keeps under the user's own config directory.
    ///
    /// `repo_path` is `.jj/repo` (`Workspace.repo_path`), and
    /// `workspace_root` the directory holding `.jj`. Without these
    /// layers `immutable_heads()` set by `jj config set --repo` has no
    /// effect, and a rewrite real jj refuses goes through.
    #[staticmethod]
    fn for_repo(repo_path: &str, workspace_root: &str) -> PyResult<Self> {
        let config = crate::config::load_config_for_repo(
            std::path::Path::new(repo_path),
            std::path::Path::new(workspace_root),
        )
        .map_err(crate::errors::map_py_err)?;
        let user_settings = UserSettings::from_config(config).map_err(crate::errors::map_py_err)?;
        Ok(Self(user_settings))
    }

    /// Returns these settings with `--config NAME=VALUE` /
    /// `--config-file PATH` layers applied, in the order given: each
    /// item is a `("config" | "config-file", text)` pair, mirroring the
    /// flags' argv order (interleavings included).
    ///
    /// Both spellings share the `CommandArg` source, which outranks every
    /// file and env layer, and layers of one source keep insertion order
    /// -- so each flag wins over every flag before it, whichever kind
    /// either is, exactly like the real CLI. Failures (a `--config`
    /// without `=`, an unreadable file, TOML that does not parse, a value
    /// whose type a setting rejects) raise `JjError` carrying the body of
    /// what `jj` prints, `Config error: ` prefix and help footer aside.
    ///
    /// Empty input clones without rebuilding, so a command given neither
    /// flag keeps its change-id RNG sequence (rebuilding would restart
    /// it -- `UserSettings::from_config` seeds a fresh RNG).
    fn with_command_args(&self, args: Vec<(String, String)>) -> PyResult<Self> {
        if args.is_empty() {
            return Ok(Self(self.0.clone()));
        }
        let mut config = self.0.config().clone();
        for (kind, text) in &args {
            match kind.as_str() {
                "config" => {
                    let layer = parse_config_pair(text).map_err(crate::errors::JjError::new_err)?;
                    config.add_layer(layer);
                }
                "config-file" => {
                    let path = std::path::PathBuf::from(text);
                    let content = std::fs::read_to_string(&path).map_err(|err| {
                        crate::errors::JjError::new_err(format!(
                            "Failed to read configuration file\n\
                             Caused by:\n\
                             1: Cannot access {}\n\
                             2: {err}",
                            path.display()
                        ))
                    })?;
                    let document: toml_edit::DocumentMut =
                        content.parse().map_err(|err: toml_edit::TomlError| {
                            crate::errors::JjError::new_err(format!(
                                "Configuration cannot be parsed as TOML document\n\
                                 Caused by: {err}\n\
                                 Hint: Check the config file: {}",
                                path.display()
                            ))
                        })?;
                    let mut layer = ConfigLayer::with_data(ConfigSource::CommandArg, document);
                    layer.path = Some(path);
                    config.add_layer(layer);
                }
                _ => {
                    return Err(crate::errors::JjError::new_err(format!(
                        "unknown config argument kind `{kind}`"
                    )));
                }
            }
        }
        let settings = UserSettings::from_config(config)
            .map_err(|err| crate::errors::JjError::new_err(error_chain_body(&err)))?;
        Ok(Self(settings))
    }

    #[getter]
    fn user_name(&self) -> &str {
        self.0.user_name()
    }

    #[getter]
    fn user_email(&self) -> &str {
        self.0.user_email()
    }

    #[getter]
    fn operation_hostname(&self) -> &str {
        self.0.operation_hostname()
    }

    #[getter]
    fn operation_username(&self) -> &str {
        self.0.operation_username()
    }

    /// The default signature (name + email + current timestamp).
    fn signature(&self) -> PySignature {
        self.0.signature().into()
    }

    /// Reads an arbitrary dotted config key (e.g. `"revsets.log"`,
    /// `"ui.default-command"`) as a string. Returns `None` if the key isn't
    /// set anywhere in the loaded config layers (including built-in
    /// defaults); raises `JjError` if it's set but isn't a string (e.g. a
    /// table or a list). No dedicated per-key getters exist elsewhere in
    /// this API on purpose -- this one generic accessor covers every
    /// string-valued config key a caller might need, the same way `jj`
    /// itself reads arbitrary config via `StackedConfig::get`.
    fn get_string(&self, key: &str) -> PyResult<Option<String>> {
        let path: jj_lib::config::ConfigNamePathBuf = key.parse().map_err(|err| {
            crate::errors::JjError::new_err(format!("invalid config key `{key}`: {err}"))
        })?;
        match self.0.config().get::<String>(path) {
            Ok(value) => Ok(Some(value)),
            Err(jj_lib::config::ConfigGetError::NotFound { .. }) => Ok(None),
            Err(err) => Err(crate::errors::map_py_err(err)),
        }
    }

    /// Reads an arbitrary dotted config key as a list of strings (e.g.
    /// `merge-tools.<name>.edit-args`). Returns `None` if unset anywhere;
    /// raises `JjError` if present but not a string list.
    fn get_string_list(&self, key: &str) -> PyResult<Option<Vec<String>>> {
        let path: jj_lib::config::ConfigNamePathBuf = key.parse().map_err(|err| {
            crate::errors::JjError::new_err(format!("invalid config key `{key}`: {err}"))
        })?;
        match self.0.config().get::<Vec<String>>(path) {
            Ok(value) => Ok(Some(value)),
            Err(jj_lib::config::ConfigGetError::NotFound { .. }) => Ok(None),
            Err(err) => Err(crate::errors::map_py_err(err)),
        }
    }

    /// Reads an arbitrary dotted config key as a boolean (e.g.
    /// `merge-tools.<name>.merge-tool-edits-conflict-markers`). Returns
    /// `None` if unset anywhere; raises `JjError` if present but not a
    /// bool.
    fn get_bool(&self, key: &str) -> PyResult<Option<bool>> {
        let path: jj_lib::config::ConfigNamePathBuf = key.parse().map_err(|err| {
            crate::errors::JjError::new_err(format!("invalid config key `{key}`: {err}"))
        })?;
        match self.0.config().get::<bool>(path) {
            Ok(value) => Ok(Some(value)),
            Err(jj_lib::config::ConfigGetError::NotFound { .. }) => Ok(None),
            Err(err) => Err(crate::errors::map_py_err(err)),
        }
    }

    /// Reads an arbitrary dotted config key as an integer (e.g.
    /// `run.jobs`). Returns `None` if unset anywhere; raises `JjError` if
    /// present but not an integer.
    fn get_int(&self, key: &str) -> PyResult<Option<i64>> {
        let path: jj_lib::config::ConfigNamePathBuf = key.parse().map_err(|err| {
            crate::errors::JjError::new_err(format!("invalid config key `{key}`: {err}"))
        })?;
        match self.0.config().get::<i64>(path) {
            Ok(value) => Ok(Some(value)),
            Err(jj_lib::config::ConfigGetError::NotFound { .. }) => Ok(None),
            Err(err) => Err(crate::errors::map_py_err(err)),
        }
    }

    /// Lists the tool names under `fix.tools` (e.g. `["clang-format", "black"]`
    /// for `fix.tools.clang-format` / `fix.tools.black`). Returns an empty
    /// list if the table is not set anywhere. Used by `jj fix` to discover
    /// which formatters to run.
    fn list_fix_tools(&self) -> PyResult<Vec<String>> {
        use jj_lib::config::ConfigGetError;
        match self.0.config().get_table("fix.tools") {
            Ok(table) => Ok(table.iter().map(|(k, _)| k.to_string()).collect()),
            Err(ConfigGetError::NotFound { .. }) => Ok(vec![]),
            Err(err) => Err(crate::errors::map_py_err(err)),
        }
    }

    /// Every layer of the stacked config, lowest precedence first: the
    /// built-in defaults, system/user/repo/workspace files (whichever
    /// exist), then env overrides. Each layer carries its source name
    /// (`"default"`, `"user"`, ...), the file it was read from (if any),
    /// and its own entries as dotted-key to TOML-syntax-value strings.
    /// `jj config list` is built on this: `--include-defaults` keeps
    /// the default layers, `--include-overridden` keeps shadowed values,
    /// and `-T` templates see each value's source and path.
    fn config_layers(&self) -> PyResult<Vec<PyConfigLayer>> {
        self.0
            .config()
            .layers()
            .iter()
            .map(|layer| {
                let mut entries = std::collections::HashMap::new();
                flatten_layer(layer.data.as_table(), String::new(), &mut entries);
                Ok(PyConfigLayer {
                    source: layer.source.to_string(),
                    path: layer.path.as_ref().map(|p| p.display().to_string()),
                    entries,
                })
            })
            .collect()
    }

    fn __repr__(&self) -> String {
        format!("UserSettings({} <{}>)", self.user_name(), self.user_email())
    }
}
