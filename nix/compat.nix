let
  flake-compatish = import (
    builtins.fetchTree (builtins.fromJSON (builtins.readFile ../flake.lock))
      .nodes.flake-compatish.locked
  );
in
flake-compatish {
  source = ../.;
  overrides = {
    self = ../.;
    nixpkgs = <nixpkgs>;
  };
}
