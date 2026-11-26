from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

from ram.assets import AssetSpec, Basket, build
from ram.rule import CONTROLS, Control, Params, multiplier, multipliers, signal, simulate

BOT = Path(__file__).resolve().parents[2] / "project-trade-t-bot"


def basket_of(E: np.ndarray, go=0.1) -> Basket:
    T, N = E.shape
    R = np.vstack([np.full(N, np.nan), E[1:] / E[:-1] - 1])
    days = [f"2000-01-{1 + i % 28:02d}" for i in range(T)]  # only used for months/years in the stats
    specs = [AssetSpec(id=f"a{j}", go=go) for j in range(N)]
    return Basket(specs=specs, labels=[s.id for s in specs], names=[s.id for s in specs], dates=days, E=E, R=R, P=E,
                  alive=np.ones((T, N), bool), ppy=252.0)


def test_multiplier_table_matches_the_notes():
    # the page "Математика чёрных лебедей", section 9: multipliers at 10% and 20% drawdown
    linear, gz, late = CONTROLS[3], CONTROLS[4], CONTROLS[7]
    assert multiplier(linear, 0.10) == pytest.approx(0.6)
    assert multiplier(linear, 0.20) == pytest.approx(0.25)
    assert multiplier(gz, 0.10) == pytest.approx(0.15 / (0.25 * 0.9))
    assert multiplier(late, 0.10) == 1.0
    assert multiplier(late, 0.20) == pytest.approx(0.6)
    assert multiplier(late, 0.40) == 0.25
    dd = np.linspace(0, 0.5, 51)
    for c in CONTROLS[2:5] + CONTROLS[6:8]:
        assert np.allclose(multipliers(c, dd), [multiplier(c, v) for v in dd])


def test_trend_goes_long_a_rising_asset_and_short_a_falling_one():
    t = np.arange(400)
    rng = np.random.default_rng(1)
    up = np.exp(0.002 * t + 0.002 * rng.standard_normal(400).cumsum())
    down = np.exp(-0.002 * t + 0.002 * rng.standard_normal(400).cumsum())
    b = basket_of(np.column_stack([up, down]))
    run = simulate(b, Params(margin_cap=0))
    assert run.pos[-1, 0] > 0 > run.pos[-1, 1]
    assert run.x[100:].mean() > 0


def test_full_size_targets_the_risk():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.01, 3000)
    b = basket_of(np.exp(np.cumsum(r))[:, None])
    sig = signal(b, Params(risk=0.10, fast=0))
    # daily vol 1% -> annual 15.9%; a full position is 0.10 / 0.159 = 0.63 of the capital
    assert np.nanmedian(sig.size[200:, 0]) == pytest.approx(0.10 / (0.01 * math.sqrt(252)), rel=0.1)


def test_band_keeps_the_position_until_a_quarter_away():
    rng = np.random.default_rng(3)
    b = basket_of(np.exp(np.cumsum(rng.normal(0.0005, 0.01, 1500)))[:, None])
    run = simulate(b, Params(margin_cap=0, cost=0))
    changes = np.flatnonzero(np.abs(np.diff(run.pos[:, 0])) > 0)
    assert len(changes) < 0.5 * len(run.pos)


def test_margin_cap_limits_the_notional():
    rng = np.random.default_rng(4)
    calm = np.exp(np.cumsum(rng.normal(0.001, 0.002, 800)))  # tiny vol: a huge full size
    b = basket_of(np.column_stack([calm, calm]), go=0.2)
    run = simulate(b, Params(margin_cap=0.5))
    assert (np.abs(run.pos).sum(axis=1) * 0.2 <= 0.5 + 1e-9).all()


def test_stop_closes_the_book_for_a_month():
    t = np.arange(600)
    price = np.where(t < 300, np.exp(0.003 * t), np.exp(0.9 - 0.04 * (t - 300)))  # a rise, then a crash
    b = basket_of(np.c_[price + 1e-9 * t], go=0.0)
    run = simulate(b, Params(risk=0.3, margin_cap=0), CONTROLS[1])
    assert (run.m == 0).any()
    zero = np.flatnonzero(run.m == 0)
    assert zero[0] + 20 in zero


def test_short_cap_zero_is_long_only(fake_sources):
    b = build([AssetSpec(id="test:A1", short_cap=0.0, carry="none")])
    run = simulate(b, Params())
    assert run.pos.min() >= 0
    assert run.pos.max() > 0


def test_control_from_dict_validates():
    with pytest.raises(ValueError):
        Control.from_dict({"name": "x", "kind": "linear", "start": 0.3, "limit": 0.2})


@pytest.mark.skipif(not (BOT / "research" / "stress_scenarios.py").exists(), reason="the trade bot's repository is not next to this one")
def test_same_as_the_bot_on_its_own_data(monkeypatch):
    """The port gives the bot's research numbers to the last digit on the bot's data (2006-2026, risk 10%)."""
    monkeypatch.chdir(BOT)
    monkeypatch.syspath_prepend(str(BOT / "src"))
    monkeypatch.syspath_prepend(str(BOT / "research"))
    try:
        import stress_scenarios as SS  # type: ignore
    except Exception as e:  # the bot's own dependencies are missing
        pytest.skip(f"the bot's research does not import: {e}")
    days, R, E = SS.long_history()
    specs = [AssetSpec(id=n, go=g, cbr=(j in SS.CBR_COLS)) for j, (n, g) in enumerate(zip(SS.NAMES, SS.GO))]
    R2 = R.copy()
    R2[0] = np.nan
    b = Basket(specs=specs, labels=SS.NAMES, names=SS.NAMES, dates=days, E=E, R=R2, P=E, alive=np.ones(E.shape, bool), ppy=252.0)
    for k in (0, 1, 7):
        ours = simulate(b, Params(), CONTROLS[k]).x
        theirs = SS.simulate(R, E, days, 0.10, SS.CONTROLS[k], cbr_cols=SS.CBR_COLS, margin=SS.GO).x
        assert np.abs(ours - theirs).max() < 1e-12
    sys.modules.pop("stress_scenarios", None)
