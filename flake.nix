{
  description = "Python bindings, CLI, and TUI for Jujutsu VCS";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    # For packaging pyjj/pyjj-cli/pyjjui (dependencies/build-system/entry
    # points read straight from each project's pyproject.toml) and for the
    # editable-install devShell (see nix/pyproject.nix, shells.pyjjui).
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";

    # Evaluates default.nix (this repo's real outputs) without the flake
    # store-copy tax; see nix/compat.nix and AGENTS.md. `nix build .#foo` /
    # `nix develop .#foo` are banned in this repo -- use
    # `nix-build -A foo` / `nix-shell -A shells.foo` instead. This input
    # only needs to exist so `nix flake lock` can pin/fetch it for
    # nix/compat.nix to read from flake.lock directly.
    flake-compatish.url = "github:lillecarl/flake-compatish";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    pyproject-nix,
    flake-compatish,
  }:
    flake-utils.lib.eachSystem nixpkgs.lib.systems.flakeExposed (system: let
      pkgs = import nixpkgs {inherit system;};
      outputs = import ./default.nix {
        inputs = {inherit nixpkgs pyproject-nix;};
        inherit system pkgs;
      };
    in {
      formatter = pkgs.alejandra;
      packages = {
        inherit (outputs) pyjj-bindings pyjj pyjj-cli pyjjui;
        default = outputs.pyjjui;
      };
      devShells = {
        inherit (outputs.shells) default pyjjui;
      };
    });
}
