"""Build a declarative-#[pymodule] lib.rs for the scratch copy from the original."""
import sys
from pathlib import Path

src_dir = Path(sys.argv[1])
orig = (src_dir / "lib.rs.orig").read_text().splitlines()
exports = Path(sys.argv[2]).read_text().split()
head = orig[:66]
body = [
    "/// Python bindings for Jujutsu VCS.",
    "#[pymodule]",
    "mod pyjj_bindings {",
    "    #[allow(non_upper_case_globals)]",
    "    #[pymodule_export]",
    '    const __version__: &str = env!("CARGO_PKG_VERSION");',
    "    #[pymodule_export]",
    '    const VERSION: &str = env!("CARGO_PKG_VERSION");',
]
for e in exports:
    path = e if e.startswith("crate::") else f"super::{e}"
    path = path.replace("debug::", "crate::debug::") if path.startswith("super::debug::") else path
    path = path.replace("super::crate::", "crate::")
    body.append("    #[pymodule_export]")
    body.append(f"    use {path};")
body.append("}")
(src_dir / "lib.rs").write_text("\n".join(head + body) + "\n")
