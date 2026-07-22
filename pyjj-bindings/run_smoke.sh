#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv /tmp/pyjj-bindings-smoke --clear
/tmp/pyjj-bindings-smoke/bin/pip install maturin
/tmp/pyjj-bindings-smoke/bin/maturin build --release -m Cargo.toml -o /tmp/pyjj-bindings-smoke/dist
/tmp/pyjj-bindings-smoke/bin/pip install --force-reinstall /tmp/pyjj-bindings-smoke/dist/pyjj_bindings-*.whl
/tmp/pyjj-bindings-smoke/bin/python3 smoke_test.py
