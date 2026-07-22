{
  lib,
  python3Packages,
  rustPlatform,
}: let
  packageVersion = (builtins.fromTOML (builtins.readFile ./Cargo.toml)).package.version;
in
  python3Packages.buildPythonPackage {
    pname = "pyjj-bindings";
    version = packageVersion;
    pyproject = true;

    # jj-lib comes from crates.io (see Cargo.toml), not a path dependency
    # into a jj monorepo checkout -- this project's own directory is its
    # complete, self-contained src. No cross-project exclude-filter needed.
    src = lib.cleanSourceWith {
      src = ./.;
      filter = path: type: baseNameOf path != "target";
    };

    cargoDeps = rustPlatform.importCargoLock {
      lockFile = ./Cargo.lock;
    };

    nativeBuildInputs = [
      rustPlatform.cargoSetupHook
      rustPlatform.maturinBuildHook
    ];

    # No tests for now; smoke-test later
    doCheck = false;
    pythonImportsCheck = [];

    env = {
      RUST_BACKTRACE = 1;
      CARGO_INCREMENTAL = "0";
    };

    meta = {
      description = "Raw PyO3 bindings for Jujutsu VCS";
      homepage = "https://github.com/jj-vcs/jj";
      license = lib.licenses.asl20;
    };
  }
