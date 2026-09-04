"""The colour engine against every style the corpus recorded.

`--color=debug` writes jj's label stacks *and* its escape sequences,
interleaved, so each golden says what style jj chose for each stack.
That makes the goldens a check on the port: for every span in every
golden, the engine must ask for the style jj used.

The goldens are a check, not a specification. They cover the stacks the
catalogue happens to reach, and a new entry brings new ones. The
specification is jj's own `cli/src/config/colors.toml` and
`cli/src/formatter.rs`, which `pyjj_cli/formatter.py` ports.
"""

import re

import pytest

from parity.corpus import GOLDEN_SUFFIX
from parity.corpus.capture import GOLDENS
from parity.corpus.catalogue import CATALOGUE
from pyjj_cli.formatter import _COLOURS, style_for

# One escape sequence, or one labelled span.
_TOKEN = re.compile(r"\x1b\[([0-9;]*)m|<<([^:]*)::(.*?)>>", re.S)

_INDEX_TO_NAME = {index: name for name, index in _COLOURS.items()}

# Attribute codes jj emits, as (code, key, value).
_ON = {"1": ("weight", "bold"), "2": ("weight", "dim"),
       "3": ("italic", True), "4": ("underline", True),
       "9": ("crossed_out", True), "7": ("reverse", True)}
_OFF = {"23": "italic", "24": "underline", "29": "crossed_out", "27": "reverse"}


def _apply(state: dict, sgr: str) -> None:
    """Fold one escape sequence into the terminal state.

    `38;5;N` is one parameter, not three, so it is consumed whole
    rather than split on its semicolons.
    """
    codes = (sgr or "0").split(";")
    i = 0
    while i < len(codes):
        code = codes[i]
        i += 1
        if code in ("38", "48"):
            key = "fg" if code == "38" else "bg"
            mode = codes[i] if i < len(codes) else ""
            if mode == "5":
                state[key] = _INDEX_TO_NAME[int(codes[i + 1])]
                i += 2
            else:  # 24-bit, which jj's palette never asks for
                state[key] = ";".join(codes[i:i + 4])
                i += 4
        elif code in ("", "0"):
            state.clear()
        elif code in _ON:
            key, value = _ON[code]
            state[key] = value
        elif code in _OFF:
            state.pop(_OFF[code], None)
        elif code == "22":
            state.pop("weight", None)
        elif code == "39":
            state.pop("fg", None)
        elif code == "49":
            state.pop("bg", None)
        else:
            raise AssertionError(f"unhandled SGR code {code!r}")


def _canonical(style: dict) -> dict:
    """A style as the state a terminal would be left in.

    `default` and absent both mean no colour: jj emits `39` for either,
    so the two cannot be told apart from the output.
    """
    out = {}
    if style.get("bold"):
        out["weight"] = "bold"
    elif style.get("dim"):
        out["weight"] = "dim"
    for name in ("italic", "underline", "crossed_out", "reverse"):
        if style.get(name):
            out[name] = True
    for name in ("fg", "bg"):
        value = style.get(name)
        if value and value != "default":
            out[name] = value
    return out


def _spans():
    """Every labelled span in every golden, with the style jj used.

    Only the entries the corpus compares. `help` is jj printing its own
    argument parser's help, which clap colours itself, in the 30-37
    range and with no labels -- nothing there says anything about jj's
    formatter.
    """
    ids = sorted(e.id for e in CATALOGUE
                 if e.bar in {"bytes", "facts", "todo"})
    for path in (GOLDENS / f"{entry_id}{GOLDEN_SUFFIX}" for entry_id in ids):
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            state: dict = {}
            for match in _TOKEN.finditer(line):
                sgr, labels, _text = match.group(1, 2, 3)
                if sgr is not None:
                    _apply(state, sgr)
                else:
                    yield path.name, number, labels, dict(state)


def test_the_corpus_recorded_some_styles():
    """A pass over no spans would prove nothing."""
    styled = [span for span in _spans() if span[3]]
    assert len(styled) > 100


def test_the_engine_asks_for_the_styles_jj_used():
    """Every label stack in the corpus resolves to jj's own style."""
    wrong = []
    for name, number, labels, observed in _spans():
        wanted = _canonical(style_for(tuple(labels.split())))
        if wanted != observed:
            wrong.append(f"{name}:{number} {labels!r}: "
                         f"jj {observed}, engine {wanted}")
    assert not wrong, "\n".join(sorted(set(wrong))[:20])
