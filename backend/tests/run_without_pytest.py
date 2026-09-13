"""Run the test suite without pytest installed.

    python backend/tests/run_without_pytest.py

Imports every `test_*.py` module in this directory and calls every zero-argument
`test_*` callable it finds, reporting failures with their assertion message and
exiting non-zero if any fail.

Why this exists: `pytest` is the intended runner (`pytest backend/tests -q`), but
the physics core was deliberately made importable with only the standard library,
and it would be a shame if verifying it required installing anything. This is
~60 lines and keeps the suite runnable anywhere Python 3.10+ exists.

It is NOT a pytest replacement -- no fixtures, no parametrize, no marks. The
suite is written to need none of those.
"""
import importlib.util
import sys
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[1]))       # backend/, so `app.*` resolves


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    files = sorted(p for p in _HERE.glob("test_*.py"))
    if not files:
        print("no test_*.py files found in", _HERE)
        return 1

    passed, failures = 0, []
    for path in files:
        print("\n%s" % path.name)
        try:
            module = _load(path)
        except Exception:
            failures.append((path.name, "<import>", traceback.format_exc()))
            print("  IMPORT FAILED")
            continue

        names = sorted(n for n in dir(module) if n.startswith("test_"))
        for name in names:
            fn = getattr(module, name)
            if not callable(fn):
                continue
            try:
                fn()
            except Exception:
                failures.append((path.name, name, traceback.format_exc()))
                print("  FAIL  %s" % name)
            else:
                passed += 1
                print("  ok    %s" % name)

    print("\n" + "=" * 72)
    print("%d passed, %d failed" % (passed, len(failures)))
    for fname, test, tb in failures:
        print("\n--- %s::%s" % (fname, test))
        print(tb.rstrip())
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
