# Review of pyjj-bindings and pyjj, 2026-10-21

Five serial reviews of `pyjj-bindings/src/*.rs` and `pyjj/pyjj/*.py`,
made against revision 61e51c3 (jj-lib 0.46.0). Line numbers refer to
that revision.

- `00-summary.md`: ranked findings and the fix order. Start here.
- `01-codegen.md`: can codegen replace the bindings? Stubs yes, wrappers no.
- `02-core.md`: errors, ids, config, and the crate-wide async/GIL audit.
- `03-repo-workspace.md`: `repo.rs`, `workspace.rs`, `commit.rs`.
- `04-leaf-rust.md`: the other Rust modules.
- `05-python.md`: the Python wrapper.

The reports say "scratchpad" for their evidence. Those probe scripts and
logs are in `evidence/` (and `evidence/r05/` for report 05). The probes
ran against a wheel built from the revision above. Large generated files
(the stub, rustdoc JSON, type-checker JSON) are not kept.
