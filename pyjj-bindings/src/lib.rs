use pyo3::prelude::*;

mod absorb;
mod annotate;
mod bisect;
mod bookmark;
mod checkout;
mod commit;
mod config;
mod conflicts;
mod converge;
mod debug;
mod errors;
mod evolution;
mod file;
mod fix;
mod gc;
mod git;
mod graph;
mod hunks;
mod ids;
mod opdiff;
mod operation;
mod oplog;
mod repo;
mod revert;
mod run;
mod revset;
mod rewrite;
mod secure_config;
mod settings;
mod tag;
mod tree;
mod workspace;

/// Python bindings for Jujutsu VCS.
#[pymodule]
mod pyjj_bindings {
    #[allow(non_upper_case_globals)]
    #[pymodule_export]
    const __version__: &str = env!("CARGO_PKG_VERSION");
    #[pymodule_export]
    const VERSION: &str = env!("CARGO_PKG_VERSION");
    #[pymodule_export]
    use crate::errors::JjError;
    #[pymodule_export]
    use crate::errors::RepoInitError;
    #[pymodule_export]
    use crate::errors::RepoLoadError;
    #[pymodule_export]
    use crate::errors::BackendError;
    #[pymodule_export]
    use crate::errors::RepoIndexError;
    #[pymodule_export]
    use crate::errors::ConfigError;
    #[pymodule_export]
    use crate::errors::TransactionError;
    #[pymodule_export]
    use crate::errors::WorkspaceInitError;
    #[pymodule_export]
    use crate::errors::WorkspaceLoadError;
    #[pymodule_export]
    use crate::errors::WorkingCopyError;
    #[pymodule_export]
    use crate::errors::CheckoutError;
    #[pymodule_export]
    use crate::errors::RevsetParseError;
    #[pymodule_export]
    use crate::errors::RevsetEvalError;
    #[pymodule_export]
    use crate::errors::GitImportError;
    #[pymodule_export]
    use crate::errors::GitExportError;
    #[pymodule_export]
    use crate::errors::GitFetchError;
    #[pymodule_export]
    use crate::errors::GitPushError;
    #[pymodule_export]
    use crate::ids::PyCommitId;
    #[pymodule_export]
    use crate::ids::PyChangeId;
    #[pymodule_export]
    use crate::ids::PyTreeId;
    #[pymodule_export]
    use crate::ids::PyFileId;
    #[pymodule_export]
    use crate::ids::PyTimestamp;
    #[pymodule_export]
    use crate::ids::PySignature;
    #[pymodule_export]
    use crate::settings::PyUserSettings;
    #[pymodule_export]
    use crate::settings::PyConfigLayer;
    #[pymodule_export]
    use crate::bookmark::PyBookmark;
    #[pymodule_export]
    use crate::bookmark::PyRemoteBookmark;
    #[pymodule_export]
    use crate::tag::PyTag;
    #[pymodule_export]
    use crate::tag::PyRemoteTag;
    #[pymodule_export]
    use crate::commit::PyCommit;
    #[pymodule_export]
    use crate::commit::PyVerification;
    #[pymodule_export]
    use crate::tree::PyDiffEntry;
    #[pymodule_export]
    use crate::tree::PyDiffStat;
    #[pymodule_export]
    use crate::operation::PyOperation;
    #[pymodule_export]
    use crate::commit::PyReadonlyRepo;
    #[pymodule_export]
    use crate::repo::PyTransaction;
    #[pymodule_export]
    use crate::repo::PyCommitBuilder;
    #[pymodule_export]
    use crate::workspace::PyWorkspace;
    #[pymodule_export]
    use crate::hunks::PyHunk;
    #[pymodule_export]
    use crate::hunks::PyUnifiedHunk;
    #[pymodule_export]
    use crate::tree::PyGitDiffFile;
    #[pymodule_export]
    use crate::annotate::PyAnnotationLine;
    #[pymodule_export]
    use crate::absorb::PyAbsorbStats;
    #[pymodule_export]
    use crate::fix::PyFileToFix;
    #[pymodule_export]
    use crate::fix::PyFixSummary;
    #[pymodule_export]
    use crate::oplog::PyOpAbandonStats;
    #[pymodule_export]
    use crate::graph::PyGraphEdge;
    #[pymodule_export]
    use crate::graph::PyGraphNode;
    #[pymodule_export]
    use crate::graph::PyGraphRenderer;
    #[pymodule_export]
    use crate::bisect::PyBisector;
    #[pymodule_export]
    use crate::bisect::PyBisectStep;
    #[pymodule_export]
    use crate::converge::PyDivergentChange;
    #[pymodule_export]
    use crate::converge::PyTruncatedEvolutionGraph;
    #[pymodule_export]
    use crate::converge::PyConvergeResult;
    #[pymodule_export]
    use crate::converge::PyConvergeTree;
    #[pymodule_export]
    use crate::converge::PyConvergedAuthor;
    #[pymodule_export]
    use crate::converge::PyConvergedDescription;
    #[pymodule_export]
    use crate::converge::PyConvergedParents;
    #[pymodule_export]
    use crate::evolution::PyEvolutionEntry;
    #[pymodule_export]
    use crate::rewrite::PyMoveCommitsStats;
    #[pymodule_export]
    use crate::opdiff::PyOperationDiff;
    #[pymodule_export]
    use crate::opdiff::PyModifiedChange;
    #[pymodule_export]
    use crate::opdiff::PyRefChange;
    #[pymodule_export]
    use crate::opdiff::PyRefTargetSummary;
    #[pymodule_export]
    use crate::run::PyRunPool;
    #[pymodule_export]
    use crate::run::PyRunSlot;
    #[pymodule_export]
    use crate::git::PyGitPushStats;
    #[pymodule_export]
    use crate::git::PyGitImportStats;
    #[pymodule_export]
    use crate::git::PyGitExportStats;
    #[pymodule_export]
    use crate::checkout::PyCheckoutStats;
    #[pymodule_export]
    use crate::checkout::SnapshotOutcome;
    #[pymodule_export]
    use crate::hunks::diff_hunks;
    #[pymodule_export]
    use crate::hunks::changed_line_ranges;
    #[pymodule_export]
    use crate::hunks::unified_hunks;
    #[pymodule_export]
    use crate::hunks::content_hunks;
    #[pymodule_export]
    use crate::secure_config::secure_config_file;
    #[pymodule_export]
    use crate::secure_config::repo_config_repo_path;
    #[pymodule_export]
    use crate::secure_config::remove_repo_config_dir;
    #[pymodule_export]
    use crate::secure_config::repo_configs_root_dir;
    #[pymodule_export]
    use crate::debug::debug_revset;
    #[pymodule_export]
    use crate::debug::debug_fileset;
    #[pymodule_export]
    use crate::debug::debug_tree;
    #[pymodule_export]
    use crate::debug::debug_copy_detection;
    #[pymodule_export]
    use crate::debug::debug_object_commit;
    #[pymodule_export]
    use crate::debug::debug_object_operation;
    #[pymodule_export]
    use crate::debug::debug_object_view;
    #[pymodule_export]
    use crate::debug::debug_object_file;
    #[pymodule_export]
    use crate::debug::debug_object_symlink;
    #[pymodule_export]
    use crate::debug::debug_object_tree;
    #[pymodule_export]
    use crate::debug::debug_index;
    #[pymodule_export]
    use crate::debug::debug_reindex;
    #[pymodule_export]
    use crate::debug::debug_index_changed_paths;
    #[pymodule_export]
    use crate::debug::debug_stacked_table;
    #[pymodule_export]
    use crate::debug::debug_init_simple;
    #[pymodule_export]
    use crate::debug::debug_working_copy;
    #[pymodule_export]
    use crate::debug::debug_local_working_copy;
    #[pymodule_export]
    use crate::debug::debug_watchman;
}
