use pyo3::prelude::*;

use jj_lib::settings::UserSettings;

use crate::ids::PySignature;

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
    /// overrides -- everything except repo/workspace config (not loaded;
    /// see `pyjj_bindings.config`'s module docs for why) and command-line
    /// `--config` (not applicable to a library).
    ///
    /// Pass `load_config=False` to skip all of that and get only jj_lib's
    /// own built-in defaults (empty user name/email, no revset aliases) --
    /// useful for hermetic tests that shouldn't depend on the machine's
    /// real jj config.
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

    fn __repr__(&self) -> String {
        format!("UserSettings({} <{}>)", self.user_name(), self.user_email())
    }
}
