"""Pytest configuration for the backend test suite.

`backend/` is not an installed package, so `app.*` only resolves if the backend
directory is on sys.path. Doing it here means `pytest` works from the repo root,
from `backend/`, or from anywhere else.

Design constraint for every test in this directory: **plain asserts, no fixtures,
no pytest-only features.** Each test is a zero-argument `test_*` function. That
keeps the suite runnable by `run_without_pytest.py` in environments where pytest
is not installed, which is exactly the situation the physics was originally
written in -- and it is why the physics modules import on the standard library
alone (see `app/domain/species.py` and the lazy `httpx` imports).
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
