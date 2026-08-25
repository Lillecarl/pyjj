{
  lib,
  python3,
  pyjj,
  renderPyproject,
  installShellFiles,
}: let
  attrs = renderPyproject {
    projectRoot = ./.;
    python = python3;
    pythonPackages = python3.pkgs // {inherit pyjj;};
  };

  # Pure text generator from the argcomplete dependency: prints the shellcode
  # registering a command name with argcomplete's protocol. Its bash/zsh
  # outputs are byte-identical (one ZSH_VERSION-aware script whose leading
  # "#compdef" line is the zsh site-functions convention), so one invocation
  # serves both shells; fish gets its own dedicated template.
  register-python-argcomplete =
    python3.pkgs.argcomplete
    + "/bin/register-python-argcomplete";
in
  python3.pkgs.buildPythonPackage (attrs
    // {
      doCheck = false;
      # Shell completion goes where nixpkgs conventions put it so any config
      # installing this package picks it up with no extra wiring:
      #   bash: share/bash-completion/completions/pyjj (lazy-loaded on first TAB)
      #   zsh:  share/zsh/site-functions/_pyjj         (compinit)
      #   fish: share/fish/vendor_completions.d/pyjj.fish
      nativeBuildInputs = (attrs.nativeBuildInputs or []) ++ [installShellFiles];
      postInstall = ''
        installShellCompletion --cmd pyjj \
          --bash <(${register-python-argcomplete} pyjj) \
          --zsh <(${register-python-argcomplete} pyjj) \
          --fish <(${register-python-argcomplete} --shell fish pyjj)
      '';
      meta =
        attrs.meta
        // {
          description = "Python CLI for Jujutsu VCS using pyjj bindings";
          homepage = "https://github.com/jj-vcs/jj";
          license = lib.licenses.asl20;
          mainProgram = "pyjj";
        };
    })
