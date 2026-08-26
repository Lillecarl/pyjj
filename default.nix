/*
  Classic (non-flake) entry point for this repo's Nix outputs, evaluated via
  flake-compatish (nix/compat.nix) instead of `nix build .#foo` / `nix
  develop .#foo` -- flakes copy the entire source tree into the store as one
  unit before evaluating anything, on every invocation. Each project here
  (pyjj-bindings/, pyjj/, pyjj-cli/, pyjjui/) is its own self-contained `src`
  (no shared monorepo source filter to keep in sync), so editing one project
  never busts another's build cache regardless of evaluation strategy -- but
  avoiding the flake store-copy still keeps iteration fast and `nix-shell`
  cheap to enter.

  Usage (never `nix build .#foo` / `nix develop .#foo` -- see AGENTS.md):

    nix-build -A pyjjui
    nix build --file . pyjjui
    nix-shell -A shells.default   # fast Rust loop for pyjj-bindings
    nix-shell -A shells.pyjjui    # editable-install Python dev loop

  flake.nix exists only to pin inputs and produce flake.lock for
  nix/compat.nix to read directly -- it has no packages/devShells outputs of
  its own (no `nix build .#foo` / `nix develop .#foo` here). This file is the
  single source of truth for what gets built.
*/
let
  flake = import ./nix/compat.nix;
in
{
  inputs ? flake.inputs,
  system ? builtins.currentSystem,
  pkgs ? import inputs.nixpkgs { inherit system; },
}:
let
  inherit (pkgs) lib;

  # The reference `jj` CLI, pinned to the release matching pyjj-bindings'
  # jj-lib crate pin (flake.nix input `jj-vcs`) -- never the machine's own
  # `jj`. Conformance tests (pyjj/tests/parity) drive this against
  # pyjj-built repos so both sides of a comparison speak the same release.
  jj = inputs.jj-vcs.packages.${system}.jujutsu;

  pyprojectLib = import ./nix/pyproject.nix {
    pyproject-nix-src = inputs.pyproject-nix;
    inherit lib;
  };

  pyjj-bindings = pkgs.callPackage ./pyjj-bindings/package.nix { };
  pyjj = pkgs.callPackage ./pyjj/package.nix {
    inherit pyjj-bindings;
    inherit (pyprojectLib) renderPyproject;
  };
  pyjj-cli = pkgs.callPackage ./pyjj-cli/package.nix {
    inherit pyjj;
    inherit (pyprojectLib) renderPyproject;
  };
  pyjjui = pkgs.callPackage ./pyjjui/package.nix {
    inherit pyjj;
    inherit (pyprojectLib) renderPyproject;
  };

  # Store-built conformance runs: the pyjj pytest suite (unit + parity vs
  # real jj) with the pinned `jj` on PATH. See nix/checks.nix.
  checks = pkgs.callPackage ./nix/checks.nix {
    inherit pyjj pyjj-cli jj;
  };

  shells = {
    # Fast local loop for pyjj-bindings (the compiled Rust extension): plain
    # nixpkgs stable rustc/cargo (pyjj-bindings needs edition 2024 / rustc
    # >=1.89, which current nixpkgs stable already ships -- no rust-overlay
    # nightly pin needed here, unlike jj's own Rust workspace).
    #
    #   nix-shell -A shells.default
    #   maturin develop -m pyjj-bindings/Cargo.toml
    default = pkgs.mkShell {
      name = "pyjj-bindings";
      packages = with pkgs; [
        cargo
        rustc
        rustfmt
        clippy
        pkg-config
        maturin
        python3
      ];
      shellHook = ''
        unset PYTHONPATH
      '';
    };

    # Editable-install dev loop for pyjj/pyjj-cli/pyjjui: source edits under
    # pyjj/, pyjj-cli/src/, pyjjui/src/ take effect immediately (no
    # PYTHONPATH, no reinstall, no Nix rebuild) via a PEP-660 editable
    # `.pth` shim pointed at $GIT_ROOT (see nix/pyproject.nix's docs on
    # renderEditablePyproject for why `root` has to be a real, non-store
    # path). pyjj-bindings (the compiled Rust extension) is *not* editable
    # here -- use `shells.default` + `maturin develop` for that, then
    # re-enter this shell to pick up the freshly built extension.
    pyjjui =
      let
        inherit (pyprojectLib) renderEditablePyproject;

        pyjjEditable = pkgs.python3.pkgs.mkPythonEditablePackage (renderEditablePyproject {
          projectRoot = ./pyjj;
          root = "$GIT_ROOT/pyjj";
          python = pkgs.python3;
          pythonPackages = pkgs.python3.pkgs // {
            inherit pyjj-bindings;
          };
        });

        pyjjCliEditable = pkgs.python3.pkgs.mkPythonEditablePackage (renderEditablePyproject {
          projectRoot = ./pyjj-cli;
          root = "$GIT_ROOT/pyjj-cli/src";
          python = pkgs.python3;
          pythonPackages = pkgs.python3.pkgs // {
            pyjj = pyjjEditable;
          };
        });

        pyjjuiEditable = pkgs.python3.pkgs.mkPythonEditablePackage (renderEditablePyproject {
          projectRoot = ./pyjjui;
          root = "$GIT_ROOT/pyjjui/src";
          python = pkgs.python3;
          pythonPackages = pkgs.python3.pkgs // {
            pyjj = pyjjEditable;
          };
        });

        pythonEnv = pkgs.python3.withPackages (
          ps:
          pyjjEditable.dependencies
          ++ pyjjCliEditable.dependencies
          ++ pyjjuiEditable.dependencies
          ++ [
            pyjjEditable
            pyjjCliEditable
            pyjjuiEditable
            ps.pytest
            ps.pytest-textual-snapshot
            ps.textual-dev
            # For pyjjui/tools/screenshot.py's SVG->PNG conversion -- cairosvg
            # specifically, not resvg: resvg's SVG parser rejects Rich's
            # clip-path syntax and silently drops all text.
            ps.cairosvg
          ]
        );
      in
      pkgs.mkShell {
        name = "pyjjui";
        packages = [ pythonEnv jj ];
        shellHook = ''
          export GIT_ROOT="$(git rev-parse --show-toplevel)"
          unset PYTHONPATH
        '';
      };
  };
in
{
  inherit
    pkgs
    lib
    flake
    shells
    jj
    checks
    ;
  inherit
    pyjj-bindings
    pyjj
    pyjj-cli
    pyjjui
    ;
  default = pyjjui;
  shell = shells.default;
}
