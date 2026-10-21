{
  lib,
  python3Packages,
  rustPlatform,
  runtimeShell,
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

    dependencies = [python3Packages.anyio];

    # Ships pyjj_bindings/_native.pyi, from pyo3's experimental-inspect.
    maturinBuildFlags = ["--generate-stubs"];

    # maturinBuildHook always passes --strip, and maturin strips the
    # library before it reads the stub data out of it ("No module named
    # _native found"). The fixup phase strips the .so anyway. A wrapper
    # on PATH, not a shell function: the hook calls maturin through `env`.
    preBuild = ''
      mkdir -p "$TMPDIR/maturin-no-strip"
      cat > "$TMPDIR/maturin-no-strip/maturin" <<EOF
      #!${runtimeShell}
      args=()
      for arg in "\$@"; do
        [[ \$arg == --strip ]] || args+=("\$arg")
      done
      exec $(command -v maturin) "\''${args[@]}"
      EOF
      chmod +x "$TMPDIR/maturin-no-strip/maturin"
      export PATH="$TMPDIR/maturin-no-strip:$PATH"
    '';

    # The stub cannot see the `*_async` methods `_async.py` installs at
    # import time; this adds them, typed like their sync methods.
    postInstall = ''
      ${python3Packages.python.interpreter} fix_stub.py \
        python/pyjj_bindings/_async.py \
        $out/${python3Packages.python.sitePackages}/pyjj_bindings/_native.pyi
    '';

    # No tests for now; smoke-test later
    doCheck = false;
    pythonImportsCheck = ["pyjj_bindings"];

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
