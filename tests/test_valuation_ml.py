"""Stage 3: server-analytic-system's valuation re-run point in time, the deflated Sharpe ratio, walk-forward ML."""
from __future__ import annotations

import numpy as np
import pytest

from ram import ml, sas, sizing, universe, valuation


def test_forward_selection_takes_the_informative_indicator_only():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((120, 6))
    y = 0.8 * X[:, 2] + 0.3 * rng.standard_normal(120)
    assert valuation.select(X, y) == [2]


def test_sector_base_pulls_a_lone_company_to_the_market():
    rng = np.random.default_rng(1)
    # sectors that hardly differ: the base of a one-company sector stays near the market
    sectors = np.array(["a"] * 40 + ["b"] * 40 + ["c"])
    y = np.r_[rng.normal(2.0, 0.5, 40), rng.normal(2.1, 0.5, 40), [3.5]]
    base = valuation.SectorBase().fit(sectors, y)
    assert abs(base(np.array(["c"]))[0] - base.overall) < 0.4 * (3.5 - base.overall)  # pulled most of the way
    # sectors far apart: each keeps its own median
    y2 = np.r_[rng.normal(2.0, 0.3, 40), rng.normal(3.0, 0.3, 40), [3.5]]
    a, b = valuation.SectorBase().fit(sectors, y2)(np.array(["a", "b"]))
    assert a == pytest.approx(2.0, abs=0.15) and b == pytest.approx(3.0, abs=0.15)


def test_valuation_finds_the_planted_mispricing():
    rng = np.random.default_rng(2)
    rows = []
    mispricing = rng.normal(0, 0.25, 90)
    for i in range(90):
        roe = rng.uniform(5, 35)
        sector = ["utilities", "energy", "financial"][i % 3]
        fair = 1.6 + {"utilities": -0.3, "energy": 0.0, "financial": 0.2}[sector] + 0.04 * (roe - 20)
        pe = float(np.exp(fair + mispricing[i]))
        rows.append({"company": f"C{i}", "tickers": [f"C{i}"], "sector": sector, "cap": pe * 100.0, "ni": 100.0,
                     "book": 500.0, "rev": 1000.0, "fcf": 50.0, "roe": roe, "g": roe * 0.5, "npm": 10.0})
    res = valuation.analyse(rows, "pe")
    assert res["r2"]["reg"] > 0.5 and res["r2"]["reg"] > res["r2"]["base"]
    assert "roe" in res["features"]
    gap = np.array(res["gaps"]["reg"])  # fair minus actual: minus the planted mispricing
    assert np.corrcoef(gap, -mispricing)[0, 1] > 0.8


def test_deflated_sharpe_discounts_the_best_of_many_noises():
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 0.03, (40, 60))
    best = noise[int(np.argmax([x.mean() / x.std(ddof=1) for x in noise]))]
    d = sizing.deflated_sharpe(best, 40)
    assert d["psr"] > 0.95 and d["dsr"] < 0.8 and d["dsr"] < d["psr"] - 0.2  # good alone, ordinary after 40 tries
    skill = rng.normal(0.02, 0.03, 120)  # monthly Sharpe 0.67 over ten years
    assert sizing.deflated_sharpe(skill, 40)["dsr"] > 0.95
    assert sizing.deflated_sharpe(best, 1)["dsr"] == pytest.approx(d["psr"])


def test_walk_forward_forecasts_do_not_see_the_future():
    rng = np.random.default_rng(4)
    data = []
    for i in range(30):
        X = rng.standard_normal((50, 3))
        data.append((i, X, X[:, 0] + 0.5 * rng.standard_normal(50)))
    keys = ["a", "b", "c"]
    first = ml.run_one(("ridge", keys, 12, data))["preds"]
    assert min(first) == 12 and max(first) == 29
    changed = data[:20] + [(i, X, -y) for i, X, y in data[20:]]  # the future turned upside down
    second = ml.run_one(("ridge", keys, 12, changed))["preds"]
    for i in range(12, 21):  # forecasts made before month 20 (and month 20's own) are the same
        assert second[i] == pytest.approx(first[i])
    assert np.corrcoef(first[29], data[29][1][:, 0])[0, 1] > 0.9  # and it learned the planted relation


def test_ticker_gaps_spread_a_company_over_both_shares():
    res = {"multiples": {"pe": {"tickers": [["SBER", "SBERP"]], "gaps": {"hyb": [0.2], "reg": [0.1], "cl": [None],
                                                                         "tree": [0.3], "nn": [0.2]}},
                         "pb": {"tickers": [["SBER", "SBERP"]], "gaps": {"hyb": [0.4]}}}}
    g = valuation.ticker_gaps(res)
    assert g["SBERP"]["sas_pe"] == 0.2 and g["SBER"]["sas_all"] == pytest.approx(0.3)


@pytest.mark.skipif(sas.sas_dir() is None or not (sas.sas_dir() / "stock_snapshot_2025-10-31").exists()
                    or not universe._year_path(2025).exists(),
                    reason="no server-analytic-system snapshot or no downloaded ISS weeks")
def test_same_valuation_as_server_analytic_system_on_its_snapshot():
    p = universe.panel()
    if "2025-10-31" not in p.dates:
        pytest.skip("the ISS weeks are not downloaded")
    r = valuation.compare_with_sas(p, "2025-10-31", valuation.mcftr_weekly(p))
    assert r["common"] >= 100 and r["multiple_rho"] > 0.99
    assert r["analyses"]["hybrid"]["rho"] > 0.85 and r["analyses"]["regression"]["rho"] > 0.8
