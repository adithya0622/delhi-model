"""Tests for cell-aware routing of adopted per-cell specialists.

The adopted specialists under artifacts/chronos2_cells/ were adopted ONLY
after beating the city specialist on the identical 48-origin holdout
(scripts/finetune_chronos2_cells.py). The routing contract — identical to the
gate evaluation's (scripts/cell_archives.py::cell_key):

* EXACT cell membership: the 0.4-degree CAMS cell containing the request
  point decides; there is NO cross-cell borrowing (nearest-center routing
  would mis-serve the training cell, whose nearest adopted center is not in
  its own cell).
* Only species with a checkpoint actually on disk are routed; everything
  else (and any point outside the adopted cells) serves the city specialist.
* predict_72hr_chronos2_finetuned() requests the routed checkpoint via
  _load_ft_pipeline(mkey, cell_subdir) — asserted at the loader seam, so
  these tests run fully offline without model weights.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.services import chronos_forecast_service as cfs


# ── cell-key math: must match scripts/cell_archives.py exactly ──

def test_cell_key_matches_evaluator_math() -> None:
    assert cfs._CELL_GRID_STEP == 0.4 and cfs._CELL_GRID_OFFSET == 0.2
    # city center (28.6139, 77.209) -> [71, 192] (the training cell)
    assert cfs._cell_key(28.6139, 77.209) == (71, 192)
    # Najafgarh-ish (28.4, 76.8) -> [70, 191]
    assert cfs._cell_key(28.41, 76.81) == (70, 191)
    # south-central (28.4, 77.2) -> [70, 192]
    assert cfs._cell_key(28.40, 77.21) == (70, 192)
    # Greater Noida (28.4, 77.6) -> [70, 193]
    assert cfs._cell_key(28.40, 77.61) == (70, 193)
    # Ghaziabad-ish (28.8, 77.6) -> [71, 193] (adopted city cell? no specialist -> {})
    assert cfs._cell_key(28.80, 77.61) == (71, 193)


# ── exact-cell routing: no cross-cell borrowing ──

def test_training_cell_never_borrows_a_neighbor_specialist() -> None:
    """The city center sits 0.214 deg from c70_192's center; nearest-center
    routing would wrongly serve it the south-cell model. Exact-cell routing
    must return nothing here (city cell has no adopted specialists)."""
    assert cfs._cell_key(28.6139, 77.209) == (71, 192)
    assert cfs.cell_specialists_for(28.6139, 77.209) == {}


def test_adopted_cells_route_pm10_to_their_own_checkpoints() -> None:
    for key, subdir in (((70, 191), "c70_191_pm10"), ((70, 192), "c70_192_pm10"), ((70, 193), "c70_193_pm10")):
        lat = 0.2 + key[0] * 0.4 + 0.05  # interior point of the cell
        lon = 0.2 + key[1] * 0.4 + 0.05
        routed = cfs.cell_specialists_for(lat, lon)
        assert routed == {"pm10": subdir}, routed


def test_outside_adopted_cells_falls_back_to_city() -> None:
    # [71, 193] hosts stations but has no adopted specialist
    assert cfs.cell_specialists_for(28.80, 77.61) == {}
    # far outside Delhi entirely
    assert cfs.cell_specialists_for(19.0, 72.8) == {}


def test_boundary_points_belong_to_exactly_one_cell() -> None:
    """Grid edges at 0.4k + 0.2: floor() assigns them to the upper band."""
    lo_edge = 0.2 + 70 * 0.4           # lower edge of band 70 = 28.2
    assert cfs._cell_key(lo_edge, 77.21) == (70, 192)
    assert cfs._cell_key(math.nextafter(lo_edge, 0.0), 77.21) == (69, 192)


# ── checkpoint-on-disk gating (graceful degradation) ──

def test_router_verifies_checkpoints_on_disk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A registry entry whose checkpoint is missing must NOT be routed."""
    monkeypatch.setattr(cfs, "_CELLS_DIR", tmp_path)
    lat, lon = 28.40, 77.21  # -> [70, 192]
    assert cfs.cell_specialists_for(lat, lon) == {}          # nothing on disk yet
    ckpt = tmp_path / "c70_192_pm10" / "species_pm10"
    ckpt.mkdir(parents=True)
    (ckpt / "adapter_config.json").write_text("{}", encoding="utf-8")
    assert cfs.cell_specialists_for(lat, lon) == {"pm10": "c70_192_pm10"}


# ── prediction plumbing: the routed subdir reaches the loader seam ──

class _RecordLoader:
    """Captures (species, subdir) calls; returns (None, reason) like a miss."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, species: str, cell_subdir: str = "") -> tuple[None, str]:
        self.calls.append((species, cell_subdir))
        return None, f"no checkpoint for {species} (test stub)"


def test_predict_passes_routed_subdirs_to_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    history = {m: [1.0] for m, _ in cfs._SPECIES}
    met = {"hourly": {"time": ["2026-09-21T00:00"] * cfs.HORIZON_HOURS}}
    rec = _RecordLoader()
    monkeypatch.setattr(cfs, "_load_ft_pipeline", rec)
    monkeypatch.setattr(cfs, "finetuned_serving_ready", lambda: True)  # offline stub
    # south-central point -> pm10 must request c70_192_pm10, others city ("")
    ok, status = cfs.predict_72hr_chronos2_finetuned(
        history, None, met, lat=28.40, lon=77.21
    )
    assert ok is None  # stub loader misses -> honest degradation
    assert status["cell_routing"]["requested"] is True
    assert status["cell_routing"]["cell_key"] == [70, 192]
    assert status["cell_routing"]["routed_species"] == ["pm10"]
    assert ("pm10", "c70_192_pm10") in rec.calls
    assert ("pm2_5", "") in rec.calls  # non-routed species use the city model


def test_predict_without_lat_lon_uses_city_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    history = {m: [1.0] for m, _ in cfs._SPECIES}
    met = {"hourly": {"time": ["2026-09-21T00:00"] * cfs.HORIZON_HOURS}}
    rec = _RecordLoader()
    monkeypatch.setattr(cfs, "_load_ft_pipeline", rec)
    monkeypatch.setattr(cfs, "finetuned_serving_ready", lambda: True)  # offline stub
    cfs.predict_72hr_chronos2_finetuned(history, None, met)
    assert all(subdir == "" for _s, subdir in rec.calls)
