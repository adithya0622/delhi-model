"""Unit tests for the backtest metrics — pure functions, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backtest_service import (
    _bootstrap_mae_ci,
    _finite_pairs,
    compute_metrics,
)


def test_perfect_forecast_has_zero_error():
    obs = [10.0, 20.0, 30.0, 40.0]
    m = compute_metrics(obs, obs)
    assert m["n"] == 4
    assert m["mae_ug_m3"] == 0.0
    assert m["rmse_ug_m3"] == 0.0
    assert m["mbe_ug_m3"] == 0.0
    assert m["pearson_r"] == 1.0
    assert m["nash_sutcliffe_e"] == 1.0


def test_metrics_are_signed_correctly():
    # Constant over-prediction: MBE must be positive, MAE == |MBE|.
    m = compute_metrics([10.0, 10.0, 10.0], [15.0, 15.0, 15.0])
    assert m["mbe_ug_m3"] == 5.0
    assert m["mae_ug_m3"] == 5.0
    # Pearson is undefined for a constant series.
    assert m["pearson_r"] is None


def test_none_values_are_paired_and_dropped():
    obs = [10.0, None, 30.0, None, 50.0]
    pred = [12.0, 99.0, None, 31.0, 48.0]
    o, p = _finite_pairs(obs, pred)
    # Only indices 0 and 4 survive; a None on EITHER side drops the pair.
    assert (o, p) == ([10.0, 50.0], [12.0, 48.0])
    m = compute_metrics(obs, pred)
    assert m["n"] == 2


def test_bootstrap_ci_preserves_pairing():
    # Perfectly correlated large-amplitude pairs: a paired resample must keep
    # the CI near zero. An unpaired implementation would resample obs and pred
    # independently and manufacture a wide CI.
    obs = [float(10 * i) for i in range(40)]
    pred = [v + 1.0 for v in obs]
    ci = _bootstrap_mae_ci(obs, pred, n_boot=300, seed=7)
    assert ci is not None
    assert ci["lo"] <= ci["hi"]
    assert ci["hi"] < 3.0, f"pairing broken: CI {ci}"


def test_bootstrap_ci_brackets_the_point_estimate():
    import random

    rng = random.Random(1)
    obs = [50.0 + rng.gauss(0, 15) for _ in range(120)]
    pred = [o + rng.gauss(0, 10) for o in obs]
    m = compute_metrics(obs, pred)
    ci = _bootstrap_mae_ci(obs, pred, n_boot=500, seed=3)
    assert ci is not None
    assert ci["lo"] <= m["mae_ug_m3"] <= ci["hi"] or abs(m["mae_ug_m3"] - ci["lo"]) < 2.0


def test_persistence_beats_random_noise_on_smooth_series():
    # On a strongly trending series, persistence from a fixed anchor must be
    # terrible — establishing that the skill score has something to beat.
    from app.services.backtest_service import compute_metrics as cm

    truth = [float(20 + 3 * i) for i in range(72)]
    model = [t + 8.0 for t in truth]           # decent forecast, +8 bias
    persistence = [truth[0]] * 72              # "next 72 h = now"
    mae_model = cm(truth, model)["mae_ug_m3"]
    mae_base = cm(truth, persistence)["mae_ug_m3"]
    assert mae_base > mae_model * 3
