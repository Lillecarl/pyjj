"""util subcommand: completion — print a shell completion script.

pyjj completes through argcomplete, not clap, so the script registers
`pyjj` with argcomplete's protocol. It is the same text `package.nix`
installs.
"""
import sys

# jj's shell names, mapped to argcomplete's. argcomplete has no elvish
# or nushell support.
_SHELLS = {"bash": "bash", "zsh": "zsh", "fish": "fish",
           "power-shell": "powershell"}


def util_completion(args) -> int:
    import argcomplete

    shell = args.shell
    if shell not in _SHELLS:
        print(f"Error: pyjj cannot generate {shell} completions; "
              f"argcomplete supports {', '.join(sorted(_SHELLS))}",
              file=sys.stderr)
        return 1
    sys.stdout.write(argcomplete.shellcode(["pyjj"], shell=_SHELLS[shell]))
    return 0
