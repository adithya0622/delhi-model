"""Unit tests for the user gate in scripts/evaluate_chronos2_station_gates.py.

Gate under test (user-set): pass = R2 > 0.8 AND (RMSE <= 15 ug/m3 OR nRMSE <= cap),
where cap defaults to 0.12, is 0.25 for PM10 (Option B, user-approved 2026-09-18)
and 0.30 for CO (user-approved 2026-09-20, evidence-based; see docs/MODEL_VALIDATION.md).
The relative-error clause mirrors species_gate in scripts/finetune_chronos2_delhi.py
so wide-scale species (PM10, CO) can pass on relative error instead of an
unreachable absolute bar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from evaluate_chronos2_station_gates import (  # noqa: E402
    GATE_NRMSE,
    GATE_R2,
    GATE_RMSE,
    RAW_RMSE_GOAL,
    SPECIES_NRMSE_CAPS,
    _npz_stored,
    gate_block,
)


def test_gate_constants_match_user_spec() -> None:
    assert (GATE_R2, GATE_RMSE, GATE_NRMSE) == (0.8, 15.0, 0.12)
    assert SPECIES_NRMSE_CAPS == {"pm10": 0.25, "co": 0.30}
    assert RAW_RMSE_GOAL == 20.0


def test_raw_goal_20_boundary_and_ordering() -> None:
    """The tightened raw bar is RMSE < 20 (strict); 15-flag stays available."""
    b = {"n": 100, "rmse": 19.99, "r2": 0.9, "nrmse": 0.5}
    g = gate_block(b)
    assert g["rmse_lt_goal"] and g["pass"]
    assert not g["rmse_le_15"]
    b20 = {"n": 100, "rmse": 20.0, "r2": 0.9, "nrmse": 0.5}
    assert not gate_block(b20)["rmse_lt_goal"]  # strict inequality
    # relative clause still rescues blocks above the raw goal
    brelic = {"n": 100, "rmse": 37.0, "r2": 0.95, "nrmse": 0.10}
    assert gate_block(brelic)["pass"]


def test_pass_on_raw_rmse_clause() -> None:
    """Narrow-scale species: RMSE at/below 15 with strong R2 passes."""
    b = {"n": 100, "mae": 6.0, "mse": 81.0, "rmse": 9.0, "r2": 0.96, "nrmse": 0.10}
    g = gate_block(b)
    assert g["evaluated"] and g["pass"]
    assert g["rmse_le_15"] and g["r2_gt_0p8"]


def test_rmse_boundary_is_inclusive() -> None:
    """RMSE exactly 15 satisfies the <= 15 clause."""
    b = {"n": 50, "rmse": 15.0, "r2": 0.9, "nrmse": 0.2}
    assert gate_block(b)["rmse_le_15"]


def test_r2_boundary_is_exclusive() -> None:
    """R2 exactly 0.8 does NOT satisfy the strict > 0.8 requirement."""
    b = {"n": 50, "rmse": 9.0, "r2": 0.8, "nrmse": 0.1}
    g = gate_block(b)
    assert not g["r2_gt_0p8"] and not g["pass"]


def test_pass_on_relative_clause_for_wide_scale_species() -> None:
    """CO-like block: huge RMSE but relative error within 0.12 passes."""
    b = {"n": 3456, "rmse": 250.0, "r2": 0.85, "nrmse": 0.10}
    g = gate_block(b)
    assert g["pass"] and g["nrmse_le_0p12"] and not g["rmse_le_15"]


def test_pm10_cap_is_0p25_option_b() -> None:
    """Option B: PM10 passes at nRMSE 0.249 (south cell) under the 0.25 cap."""
    south = {"n": 3456, "rmse": 102.49, "r2": 0.9627, "nrmse": 0.2490}
    g = gate_block(south, nrmse_cap=SPECIES_NRMSE_CAPS["pm10"])
    assert g["pass"] and g["nrmse_within_cap"] and not g["rmse_le_15"]
    # ...but the same block still fails the original 0.12 bar
    assert not g["nrmse_le_0p12"]


def test_pm10_just_above_cap_still_fails() -> None:
    """nRMSE 0.26 exceeds the PM10 cap -> fails even with high R2."""
    b = {"n": 3456, "rmse": 100.0, "r2": 0.95, "nrmse": 0.26}
    assert not gate_block(b, nrmse_cap=SPECIES_NRMSE_CAPS["pm10"])["pass"]


def test_co_cap_is_0p30_evidence_based() -> None:
    """CO cap amended 2026-09-20 (user-approved): measured floor 0.232-0.323.

    The real city-cell numbers (nRMSE 0.293, gate report) pass under 0.30 but
    would fail the original 0.12 bar; above-floor values still fail.
    """
    city = {"n": 3456, "rmse": 249.47, "r2": 0.8118, "nrmse": 0.2930}
    g = gate_block(city, nrmse_cap=SPECIES_NRMSE_CAPS["co"])
    assert g["pass"] and g["nrmse_within_cap"] and g["nrmse_cap"] == 0.30
    # ...but the same block still fails the original 0.12 bar
    assert not g["nrmse_le_0p12"]
    above_floor = {"n": 3456, "rmse": 300.0, "r2": 0.80, "nrmse": 0.32}
    assert not gate_block(above_floor, nrmse_cap=SPECIES_NRMSE_CAPS["co"])["pass"]


def test_fail_like_current_co() -> None:
    """The published CO block (nRMSE 0.2882, R2 0.8178) must FAIL the gate."""
    b = {"n": 3456, "rmse": 245.45, "r2": 0.8178, "nrmse": 0.2882}
    assert not gate_block(b)["pass"]


def test_low_r2_fails_even_with_tiny_rmse() -> None:
    """A degenerate flat predictor with tiny RMSE still fails on R2."""
    b = {"n": 100, "rmse": 3.0, "r2": 0.5, "nrmse": 0.05}
    assert not gate_block(b)["pass"]


def test_high_rmse_with_bad_nrmse_fails() -> None:
    b = {"n": 100, "rmse": 40.0, "r2": 0.9, "nrmse": 0.3}
    assert not gate_block(b)["pass"]


def test_empty_block_is_not_a_pass() -> None:
    g = gate_block({"n": 0})
    assert not g["evaluated"] and not g["pass"]
    assert not gate_block({})["pass"]


# ------------------------------------------------- stamp-keyed npz loading --

def _write_npz(path, origins, preds, stamps=None) -> None:
    import numpy as np

    payload = {"origins": np.array(origins, dtype=np.int64),
               "preds": np.stack([np.asarray(p, dtype=float) for p in preds])}
    if stamps is not None:
        payload["stamps"] = np.array([str(s) for s in stamps])
    np.savez_compressed(path, **payload)


def test_npz_stored_matches_by_timestamp_across_index_bases(tmp_path) -> None:
    """The regression that bit the adopted per-cell forecasts: a file written
    against a 48-month series (origins 26328..) must still be found by a
    14-month caller (origins 1488..) when the wall-clock stamps agree."""
    from datetime import datetime, timedelta

    stamps = [datetime(2025, 9, 13) + timedelta(hours=i) for i in range(240)]
    preds = [[float(i)] * 3 for i in range(240)]
    big_base_origins = [100000 + i for i in (0, 5, 10)]
    _write_npz(tmp_path / "f.npz", big_base_origins,
               [preds[i] for i in (0, 5, 10)], [stamps[i] for i in (0, 5, 10)])
    stored = _npz_stored(tmp_path / "f.npz", stamps)
    assert set(stored) == {0, 5, 10}
    assert (stored[5] == preds[5]).all()


def test_npz_stored_legacy_index_file_still_loads(tmp_path) -> None:
    """Legacy index-only files (no stamps array) load by index unchanged."""
    _write_npz(tmp_path / "legacy.npz", [3, 7], [[1.0] * 2, [2.0] * 2])
    stored = _npz_stored(tmp_path / "legacy.npz", stamps=["ignored"])
    assert set(stored) == {3, 7} and stored[7][0] == 2.0


def test_npz_stored_drops_stamps_outside_caller_series(tmp_path) -> None:
    """Stamps the caller's series does not contain are silently dropped."""
    from datetime import datetime, timedelta

    stamps = [datetime(2026, 1, 1) + timedelta(hours=i) for i in range(48)]
    _write_npz(tmp_path / "f.npz", [0, 1], [[1.0], [2.0]],
               [datetime(2025, 1, 1), stamps[3]])
    stored = _npz_stored(tmp_path / "f.npz", stamps)
    assert set(stored) == {3}
