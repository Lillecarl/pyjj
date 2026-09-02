# cli package — per-command argparse registrations.
# Each module exposes `add_parsers(sub)` that registers its top-level
# command(s) onto the shared `subparsers` object. No heavy imports here
# (no pyjj, no pydantic) so `build_parser()` stays fast for --help/<TAB>.
