"""Parts of jj's argument surface pyjj-cli does not intend to accept.

Everything here is a decision, not a gap, so each entry carries the
reason. `cli_surface` subtracts these before it reports, and the test
asserts every entry still corresponds to something jj actually has --
an exclusion for a flag jj dropped is stale, and stale exclusions are
how a coverage ledger rots.

The bar for an entry is that implementing it would mean pretending:
either the behaviour cannot exist here (no built-in TUI, no embedded
copy of jj's manual), or accepting the flag silently would make
pyjj-cli disagree with jj while looking like it agreed.

"Not implemented yet" is NOT a reason. Those stay in the baseline,
where they are counted.
"""

# Whole subcommands.
EXCLUDED_COMMANDS = {
    "gerrit upload": (
        "Uploads a change to a Gerrit server. There is no server to talk "
        "to in the parity harness, and no way to compare the result "
        "against jj without one, so the command has no testable "
        "behaviour here. The parity suite excludes `gerrit` for the same "
        "reason."
    ),
}

# {subcommand: {flag: reason}}. The root command is "".
EXCLUDED_FLAGS = {
    "": {
        "--no-integrate-operation": (
            "Turns off jj's automatic merging of operations that were "
            "created concurrently. pyjj-cli never performs that "
            "integration, so there is nothing for the flag to turn off, "
            "and accepting it would imply the behaviour exists. `jj op "
            "integrate` is excluded from the parity suite for the same "
            "reason: the harness runs one operation at a time."
        ),
    },
    "help": {
        "-k": "See --keyword.",
        "--keyword": (
            "Prints a documentation topic compiled into jj's own binary. "
            "pyjj-cli has no copy of jj's manual, and shipping one would "
            "be a snapshot that silently ages. `util config-schema` is a "
            "strict xfail in the parity suite for the same reason."
        ),
    },
}

# Flags that are interactive by nature: they hand control to a TUI jj
# builds in and pyjj-cli does not have. Listed per command so a future
# built-in editor can remove them one at a time.
_INTERACTIVE = (
    "Opens jj's built-in diff editor. pyjj-cli has no built-in editor "
    "and takes `--tool` instead, so accepting `-i` would either do "
    "nothing or silently pick a different editor than jj would. The "
    "parity harness cannot drive a TUI either -- its editor-based "
    "scenarios all script an external tool."
)
for _command in ("commit", "split", "squash", "restore"):
    EXCLUDED_FLAGS.setdefault(_command, {})
    EXCLUDED_FLAGS[_command]["-i"] = "See --interactive."
    EXCLUDED_FLAGS[_command]["--interactive"] = _INTERACTIVE
del _command


def excluded_flags(command: str) -> set[str]:
    return set(EXCLUDED_FLAGS.get(command, {}))


def reasons() -> dict[str, dict[str, str]]:
    """Everything excluded, for the report and for staleness checking."""
    return {"commands": EXCLUDED_COMMANDS, "flags": EXCLUDED_FLAGS}
