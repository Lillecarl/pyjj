/*
  Thin wrapper around pyproject-nix for pyjj/pyjj-cli/pyjjui: reads each
  project's own pyproject.toml (dependencies, build-system, entry points)
  instead of hand-duplicating that metadata in Nix, for both a normal
  package build (renderPyproject) and a live-editable one
  (renderEditablePyproject, backing devShells.pyjjui's dev loop -- see
  flake.nix). Pattern mirrors ~/Code/nanopynix's default.nix.
*/
{
  pyproject-nix-src,
  lib,
}: let
  pyproject-nix = import pyproject-nix-src {inherit lib;};
in {
  renderPyproject = {
    projectRoot,
    python,
    pythonPackages ? python.pkgs,
  }:
    (pyproject-nix.lib.project.loadPyproject {inherit projectRoot;}).renderers.buildPythonPackage {
      inherit python pythonPackages;
    };

  # `root` must be a real filesystem path outside the Nix store (typically
  # "$GIT_ROOT/<project>[/src]", with $GIT_ROOT exported by the consuming
  # devShell's shellHook at *shell-entry* time) -- flakes copy `projectRoot`
  # into the store even under `nix develop`, so defaulting to it here would
  # point the editable install at a read-only, unedited snapshot. The
  # generated `.pth` file expands `$VARS` in `root` via
  # `os.path.expandvars` at Python *import* time, not Nix eval time, so the
  # shell-style `$GIT_ROOT` reference is deliberately left unexpanded here.
  renderEditablePyproject = {
    projectRoot,
    root,
    python,
    pythonPackages ? python.pkgs,
    extras ? [],
  }:
    (pyproject-nix.lib.project.loadPyproject {inherit projectRoot;}).renderers.mkPythonEditablePackage {
      inherit root python pythonPackages extras;
    };
}
