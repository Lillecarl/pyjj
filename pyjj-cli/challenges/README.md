# Agent CTF

Challenges an agent solves in a throwaway repo, armed with nothing but the
pyjj skill. Two uses, both deliberate:

1. **Skill verification** — a blind solver that finishes proves the skill
   teaches the workflow, not just the vocabulary.
2. **pyjj weakness finder** — every place a solver stalls, guesses, or
   works around the CLI is a bug report against pyjj or the skill.

## Layout

- `harness.py` — builds arenas, prints solver bundles, runs checks.
- `c_<name>.py` — one challenge: `setup(ctx)`, `PROMPT`, `check(ctx)`.
  `setup` drives the CLI (same path a solver uses); `check` may use the
  session API (it runs here, not in the solver).

## Running

Inside an env with `pyjj` importable (the `tests` app or the pyjjui shell):

```
python harness.py list
python harness.py run restack --arena /tmp/ctf/restack --pyjj-bin <bin>
python harness.py bundle restack --arena /tmp/ctf/restack   # solver prompt
python harness.py check restack --arena /tmp/ctf/restack
```

`--pyjj-bin` should point at a store-built `pyjj` (`nix build --file .
pyjj-cli`); the binary path is baked into the solver bundle so the solver
needs no Python env of its own.

## Blind protocol

1. `run` the challenge (verifies it starts unsolved).
2. `bundle` the prompt into a **fresh** subagent with: the bundle text and
   nothing else. It must not read `challenges/` (the answer key) and must
   stay inside the arena. VCS use is the task here, so it is authorized.
3. `check` the arena. A failure is data: fix the skill, the challenge, or
   pyjj itself — in that order of suspicion.
