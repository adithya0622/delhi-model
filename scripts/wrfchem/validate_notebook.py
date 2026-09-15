"""Validate every code cell of the generated Kaggle WRF-Chem notebook offline.

What it checks (no compilers, no downloads):
  1. The notebook is valid nbformat-4 JSON with code cells that all parse.
  2. Cross-cell names: every bare Name loaded by a cell is either a builtin,
     assigned in some code cell, imported there, or a known runtime global.
     This catches NameError-class bugs such as the v5 SPEC_DIR one.
  3. The mechanism set survives into the emitted namelist text
     (chem_opt=112 / emiss_opt=8 / emiss_inpt_opt=111 / phot_opt=2),
     emission files use the 'emissions_zdim' dimension name, and no stale
     v5 fragments remain in code cells.

Usage:
    python scripts/wrfchem/validate_notebook.py                # this repo's notebook
    python scripts/wrfchem/validate_notebook.py path/to.ipynb  # any notebook

Exit code 0 = all checks pass; 1 = a problem is listed (with cell numbers).
"""

from __future__ import annotations

import argparse
import ast
import json
import keyword
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_NB = _ROOT / "scripts" / "wrfchem" / "kaggle_wrfchem_run.ipynb"

# Names no cell defines but the code may use anyway: keywords/builtins are
# handled separately; these are runtime or shared-plumbing globals.
ALLOWED_GLOBALS = {
    "np", "Dataset", "UserSecretsClient", "CFG", "GASES", "AERS", "MW",
    "VOC_FRAC", "DIURNAL", "SECTORS", "EF_CROPLAND", "DH_MJ_KG",
    "anthro_gas", "anthro_aer", "fire_by_day", "days", "la_ed", "lo_ed",
    "nla", "nlo", "cell_m2", "species", "la_sorted", "order", "row_of",
    "map_to_grid", "edgar_species", "mol_km2_hr", "ug_m2_s",
    "fire_flux_grid", "firms_rows", "fire_gas", "fire_aer", "nox", "voc",
}

MECHANISM_KEEP = ("chem_opt = 112, 112", "emiss_opt = 8, 8",
                  "emiss_inpt_opt = 111, 111", "phot_opt = 2, 2",
                  '"emissions_zdim", CFG["KEMIT"]',
                  '("Time", "emissions_zdim", "south_north", "west_east")',
                  '"./configure", "chem", "kpp"', '"KEMIT": 1')
MECHANISM_STALE = ("chem_opt = 301", "phot_opt = 3", "num_land_cat = 24")


class NameUse(ast.NodeVisitor):
    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.stored: list[str] = []

    def visit_Name(self, node: ast.Name) -> None:
        (self.stored if isinstance(node.ctx, (ast.Store,)) else self.loaded).append(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stored.append(node.name)
        args = node.args
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            self.stored.append(a.arg)
        if args.vararg:
            self.stored.append(args.vararg.arg)
        if args.kwarg:
            self.stored.append(args.kwarg.arg)
        for dec in node.decorator_list:
            self.visit(dec)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stored.append(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.stored.append((a.asname or a.name).split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            if a.name != "*":
                self.stored.append(a.asname or a.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        for stmt in node.body:
            self.visit(stmt)
        if node.name:
            self.stored.append(node.name)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.stored.append(node.target.id)
        self.visit(node.value)


def code_text(nb: dict) -> str:
    return "\n".join(
        "".join(c.get("source", [])) for c in nb["cells"]
        if c.get("cell_type") == "code"
    )


def check(path: Path) -> list[str]:
    problems: list[str] = []
    nb = json.loads(path.read_text(encoding="utf-8"))
    assert nb.get("nbformat") == 4, f"{path.name}: not nbformat 4"
    code_cells = [(i, "".join(c.get("source", [])))
                  for i, c in enumerate(nb["cells"])
                  if c.get("cell_type") == "code"]
    print(f"{path.name}: {len(nb['cells'])} cells, {len(code_cells)} code")

    defined: set[str] = set()
    per_cell: list[tuple[int, NameUse]] = []
    for idx, source in code_cells:
        try:
            tree = ast.parse(source, filename=f"cell-{idx}")
        except SyntaxError as exc:
            problems.append(f"cell {idx}: SyntaxError: {exc}")
            continue
        visitor = NameUse()
        visitor.visit(tree)
        per_cell.append((idx, visitor))
        defined |= set(visitor.stored)

    import builtins
    known = defined | ALLOWED_GLOBALS | set(dir(builtins)) | set(keyword.kwlist)
    for idx, visitor in per_cell:
        for name in sorted(set(visitor.loaded) - known):
            problems.append(f"cell {idx}: name {name!r} is never assigned or imported")
    return problems


def contract_checks(path: Path) -> list[str]:
    problems: list[str] = []
    code = code_text(json.loads(path.read_text(encoding="utf-8")))
    for needle in MECHANISM_KEEP:
        if needle not in code:
            problems.append(f"missing verified fragment in code cells: {needle!r}")
    for stale in MECHANISM_STALE:
        if stale in code:
            problems.append(f"stale v5 fragment still present: {stale!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebook", nargs="?", type=Path, default=_DEFAULT_NB)
    args = parser.parse_args()

    problems = check(args.notebook) + contract_checks(args.notebook)
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  x {p}")
        return 1
    print("validate_notebook: all checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())