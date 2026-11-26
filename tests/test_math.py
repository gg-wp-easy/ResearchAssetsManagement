from __future__ import annotations

import math

import numpy as np
import pytest

from ram import allocation, sizing, tails
from ram.assets import despike, excess_index
from ram.bootstrap import path_drawdowns
from ram.regimes import fit_hmm2
from ram.rule import CONTROLS
from ram.sources import _stitch
from datetime import date


def test_gpd_recovers_the_tail_index_of_student_t():
    rng = np.random.default_rng(0)
    x = rng.standard_t(3, 200_000)  # xi = 1/3
    _, _, xi, _ = tails.gpd_tail(x, 0.98)
    assert xi == pytest.approx(1 / 3, abs=0.07)
    assert tails.hill(x, 2000) == pytest.approx(1 / 3, abs=0.06)


def test_evt_var_close_to_the_history_for_a_large_sample():
    rng = np.random.default_rng(1)
    x = rng.standard_t(4, 100_000) * 0.01
    t = tails.tail_numbers(x, 252)
    row = next(r for r in t["levels"] if r["q"] == 0.99)
    evt, normal, hist = row["var"]
    assert evt == pytest.approx(hist, rel=0.05)
    assert normal < hist  # the normal misses the fat tail
    assert row["es"][0] > evt


def test_kelly_and_sharpe():
    rng = np.random.default_rng(2)
    x = rng.normal(0.10 / 252, 0.10 / math.sqrt(252), 252 * 40)
    k = sizing.kelly(x, 252)
    assert k["f_star"] == pytest.approx(k["mu"] / k["vol"] ** 2)
    assert 0.9 < k["c_star"] < 1
    s = sizing.significance(x, 252)
    assert s["se"] == pytest.approx(math.sqrt((1 + s["sharpe"] ** 2 / 2) / 40), rel=1e-6)
    assert sizing.expected_max_sharpe(20, 1 / math.sqrt(3)) == pytest.approx(1.07, abs=0.1)


def test_risk_parity_equalizes_contributions():
    rng = np.random.default_rng(3)
    X = rng.normal(0, 1, (300, 3)) * np.array([0.01, 0.02, 0.04])
    w = allocation.weights("erc", X)
    cov = np.cov(X, rowvar=False)
    rc = w * (cov @ w)
    assert np.allclose(rc, rc.mean(), rtol=1e-4)
    for m, _ in allocation.METHODS:
        w = allocation.weights(m, X)
        assert w.sum() == pytest.approx(1) and (w >= -1e-12).all()


def test_hmm_finds_the_volatile_state():
    rng = np.random.default_rng(4)
    s = np.zeros(1200, int)
    for t in range(1, 1200):
        s[t] = s[t - 1] if rng.random() < (0.98 if s[t - 1] == 0 else 0.9) else 1 - s[t - 1]
    y = np.where(s == 0, rng.normal(0.002, 0.01, 1200), rng.normal(-0.01, 0.04, 1200))
    fit = fit_hmm2(y)
    assert fit["sd"][1] == pytest.approx(0.04, rel=0.2)
    assert fit["sd"][0] == pytest.approx(0.01, rel=0.2)
    hit = ((fit["smoothed"][:, 1] > 0.5) == (s == 1)).mean()
    assert hit > 0.9


def test_bootstrap_control_lowers_the_drawdown():
    rng = np.random.default_rng(5)
    paths = rng.normal(0.0003, 0.012, (2000, 756))
    none = path_drawdowns(paths, CONTROLS[0])
    linear = path_drawdowns(paths, CONTROLS[3])
    assert (linear > 0.25).mean() < (none > 0.25).mean()


def test_excess_index_pays_the_carry_per_calendar_day():
    days = ["2024-01-05", "2024-01-08"]  # Friday -> Monday: three days of carry
    e = excess_index(days, np.array([100.0, 100.0]), np.array([0.365, 0.365]))
    assert e[-1] == pytest.approx(1 - 0.003)


def test_despike_drops_a_flip_and_keeps_a_crash():
    rng = np.random.default_rng(6)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    days = [str(i) for i in range(300)]
    bad = px.copy()
    bad[150] *= 1.4  # a bad print
    _, clean, n = despike(days, bad)
    assert n == 1 and len(clean) == 299
    crash = px.copy()
    crash[200:] *= 0.6  # a real fall stays
    _, kept, n = despike(days, crash)
    assert n == 0


def test_stitch_adds_no_jump_at_the_roll():
    a = {"2024-01-02": 100.0, "2024-01-03": 101.0, "2024-01-04": 102.0}
    b = {"2024-01-03": 110.0, "2024-01-04": 111.0, "2024-01-05": 112.0}
    days, values, last = _stitch({"A": a, "B": b}, {"A": date(2024, 1, 10), "B": date(2024, 3, 10)}, 7)
    assert last == "B"
    r = np.diff(np.log(values))
    assert np.abs(r).max() < 0.02  # 101 -> 110 is not a return
    assert values[-1] == 112.0
