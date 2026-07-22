{
  lib,
  python3,
  pyjj-bindings,
  renderPyproject,
}: let
  attrs = renderPyproject {
    projectRoot = ./.;
    python = python3;
    pythonPackages = python3.pkgs // {inherit pyjj-bindings;};
  };
in
  python3.pkgs.buildPythonPackage (attrs
    // {
      doCheck = false;
      meta =
        attrs.meta
        // {
          description = "Pythonic API for Jujutsu VCS, built on pyjj-bindings";
          homepage = "https://github.com/jj-vcs/jj";
          license = lib.licenses.asl20;
        };
    })
