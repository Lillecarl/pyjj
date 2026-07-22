#!/usr/bin/env python3
"""Smoke test for the pyjj_bindings native module."""
import pyjj_bindings

print("pyjj_bindings module loaded successfully")
print(f"pyjj_bindings exports: {[x for x in dir(pyjj_bindings) if not x.startswith('_')]}")
print(f"pyjj_bindings version: {pyjj_bindings.__version__}")

# Test exception classes
assert pyjj_bindings.JjError.__name__ == "JjError"
print(f"JjError: {pyjj_bindings.JjError}")

# Test UserSettings
settings = pyjj_bindings.UserSettings()
print(f"UserSettings created: {settings}")

# Test ID types
cid = pyjj_bindings.CommitId("a" * 64)
print(f"CommitId: {cid}")
assert str(cid) == "a" * 64

cid2 = pyjj_bindings.ChangeId("b" * 64)
print(f"ChangeId: {cid2}")

print("\n--- All smoke tests passed! ---")
