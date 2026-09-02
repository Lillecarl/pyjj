/*
  Conformance checks: the pyjj pytest suite -- unit tests plus the
  differential parity suite against real jj (pyjj/tests/parity) -- run
  here with the version-PINNED jj binary on PATH, so a store-built check
  can never silently compare against whatever jj happens to be installed.

  Both Python layers come in as real (non-editable) packages: `pyjj`
  propagated by `pyjj-cli`, exactly what a user's profile would contain.
  The check copies the pyjj project directory (pyproject.toml carries the
  pytest config, notably anyio's auto mode) into a writable build dir and
  runs pytest there; `pyjj` resolves from site-packages, never from the
  source tree sitting next to the tests.
*/
{
  lib,
  runCommand,
  python3,
  pyjj,
  pyjj-cli,
  jj,
  gitMinimal,
  openssh,
}:

let
  pythonEnv = python3.withPackages (
    ps: [
      pyjj
      pyjj-cli
      ps.pytest
      ps.anyio
    ]
  );

  # Impure pytest args passthrough for human workflow:
  #   PYTEST_ARGS="-k test_absorb -xvs" nix build --impure --file . checks.pyjj-conformance
  # or via the `tests` app:
  #   PYTEST_ARGS="-k test_absorb -q" nix run --impure --file . tests
  # In pure evaluation (CI, no --impure) builtins.getEnv returns "" and the
  # default "-q" is used, so existing `nix build --file . checks.pyjj-conformance`
  # stays pure and hermetic.
  pytestArgs = builtins.getEnv "PYTEST_ARGS";
  pytestArgsStr = if pytestArgs == "" then "-q" else pytestArgs;
in
{
  pyjj-conformance =
    runCommand "pyjj-conformance"
      {
        nativeBuildInputs = [
          pythonEnv
          jj
          # The clone/remote fixtures seed bare Git remotes through the real
          # `git` binary; minimal is enough -- no perl-based extras needed.
          gitMinimal
          # The signing tests generate a throwaway key via ssh-keygen.
          openssh
        ];
        # Pin the comparison binary explicitly rather than trusting PATH order.
        env.PYJJ_PARITY_JJ = "${lib.getExe jj}";
      }
      ''
        export HOME="$TMPDIR/home"
        export PYTHONDONTWRITEBYTECODE=1
        mkdir -p "$HOME"

        cp -r ${./../pyjj} ./proj
        chmod -R u+w ./proj
        cd ./proj

        # shellcheck disable=SC2086
        pytest tests ${pytestArgsStr}
        touch "$out"
      '';
}
