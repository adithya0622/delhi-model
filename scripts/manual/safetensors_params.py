"""Read safetensors headers and report exact tensor-element counts.

Usage:
    python scripts/manual/safetensors_params.py <file.safetensors> [more files...]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def count(path: Path) -> tuple[int, int, dict[str, list[int]]]:
    with path.open("rb") as fh:
        n = int.from_bytes(fh.read(8), "little")
        header = json.loads(fh.read(n))
    total = 0
    tensors: dict[str, list[int]] = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        shape = meta.get("shape", [])
        total += math.prod(shape) if shape else 1
        tensors[name] = shape
    return total, len(tensors), tensors


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.is_file():
            print(f"{path}: not found")
            continue
        total, tensors, shapes = count(path)
        print(f"{path.name}: {tensors:,} tensors, {total:,} parameters ({total/1e6:.2f} M)")
        for name in list(shapes)[:6]:
            print(f"    {name}: {shapes[name]}")
        if len(shapes) > 6:
            print(f"    ... and {len(shapes) - 6} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())