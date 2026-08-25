{
  description = "Python bindings, CLI, and TUI for Jujutsu VCS";

  inputs = {
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

    # The reference `jj` binary, pinned to the same upstream release as
    # pyjj-bindings' jj-lib crate dependency (see that Cargo.toml -- keep
    # the two in sync when bumping). The conformance/parity suite drives
    # this binary against pyjj-built repos; pinning it here means tests
    # always run against the exact jj version the bindings were built
    # against, not whatever `jj` happens to be on PATH. Deliberately left
    # unfollowed: jj builds with the rustPlatform of the nixpkgs *it*
    # pins, which is what its own CI tested that release with.
    jj-vcs.url = "github:jj-vcs/jj/v0.43.0";
  };

  # This flake exists only to pin inputs and produce flake.lock for
  # nix/compat.nix (flake-compatish) to read directly -- it is never built or
  # developed against via `nix build .#foo` / `nix develop .#foo`, so there
  # are no per-system outputs to fan out here. See default.nix and
  # AGENTS.md's "Reproducible builds" section for the real entry points.
  outputs = { ... }: { };
}
