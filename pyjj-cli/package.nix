{
  lib,
  python3,
  pyjj,
  renderPyproject,
}: let
  attrs = renderPyproject {
    projectRoot = ./.;
    python = python3;
    pythonPackages = python3.pkgs // {inherit pyjj;};
  };
in
  python3.pkgs.buildPythonPackage (attrs
    // {
      doCheck = false;
      meta =
        attrs.meta
        // {
          description = "Python CLI for Jujutsu VCS using pyjj bindings";
          homepage = "https://github.com/jj-vcs/jj";
          license = lib.licenses.asl20;
          mainProgram = "pyjj";
        };
    })
