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

        pytest tests -q
        touch "$out"
      '';
}
