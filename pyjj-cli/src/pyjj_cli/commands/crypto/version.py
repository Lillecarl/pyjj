"""crypto subcommand: version."""
import sys

import pyjj

def version(args) -> int:
    print("pyjj-cli v0.1.0")
    print(f"  pyjj (Rust bindings): v{pyjj.VERSION}")
    print(f"  Python: {sys.version}")
    return 0
