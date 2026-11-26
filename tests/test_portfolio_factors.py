"""Stage 1 and 2 of the server-analytic-system integration: total returns of MOEX shares, shrinkage and HRP, the portfolio
with given weights, the factor lab."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from conftest import business_days, random_walk
from ram import allocation, factors, sas, sources, universe
from ram.assets import AssetSpec, build
from ram.rule import Params, signal, simulate
from ram.store import Series
from ram.study import run_study


@pytest.fixture
def sas_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("RAM_SAS_DATA", str(tmp_path))
    sas._cache.clear()
    yield tmp_path
    sas._cache.clear()


def test_total_return_adds_the_dividend_and_brings_the_split_to_today(sas_folder, monkeypatch):
    # raw prices: 100 until the last day to buy, 90 without the dividend of 10, then a 1:10 split -> 9;
    # T-Invest keeps the dividend on today's share count: 1
    (sas_folder / "tbank_dividends.csv").write_text(
        "ticker,record_date,last_buy_date,dividend_net,currency\nXXX,2020-01-08,2020-01-07,1.0,rub\n")
    monkeypatch.setattr(sources, "moex_splits", lambda: {"XXX": [("2020-01-10", 10.0)]})
    days = ["2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10", "2020-01-13"]
    raw = Series(id="moex:shares:XXX", name="x", currency="RUB", dates=days, values=np.array([100, 100, 90, 90, 9, 9.0]))
    s = sources.total_return(raw, "XXX")
    assert s.values == pytest.approx(np.full(6, 9.0))  # the dividend and the split leave no move
    assert "сплиты ISS" in s.note and "1 выплат" in s.note


def test_without_the_folder_a_share_stays_a_price_return(tmp_path, monkeypatch):
    monkeypatch.setenv("RAM_SAS_DATA", str(tmp_path / "missing"))
    sas._cache.clear()
    monkeypatch.setattr(sources, "moex_splits", lambda: {})
    raw = Series(id="moex:shares:X", name="x", currency="RUB", dates=["2020-01-06", "2020-01-07"], values=np.array([1.0, 2.0]))
    s = sources.total_return(raw, "X")
    assert s.values.tolist() == [1.0, 2.0] and "ценовая доходность" in s.note


def test_a_round_jump_is_taken_for_an_unlisted_split():
    days = business_days("2015-01-12", 6)
    px, found = sources.unlisted_splits(days, np.array([0.011, 0.0112, 1.15, 1.2, 1.18, 1.21]))
    assert found == [(days[2], 100)]
    assert px[1] == pytest.approx(1.12)
    _, none = sources.unlisted_splits(days, np.array([10, 5, 4, 4.2, 2.1, 2.0]))  # a crash halves, it is not a split
    assert none == []


def test_ledoit_wolf_intensity_falls_with_the_sample_and_stays_positive_definite():
    rng = np.random.default_rng(2)
    C = np.eye(8)
    C[:4, :4] = C[4:, 4:] = 0.7
    np.fill_diagonal(C, 1)
    L = np.linalg.cholesky(C)
    deltas = []
    for t in (52, 520, 5200):
        X = rng.standard_normal((t, 8)) @ L.T * 0.03
        cov, d = allocation.shrunk_cov(X)
        assert 0 <= d <= 1 and np.linalg.eigvalsh(cov).min() > 0
        assert np.diag(cov) == pytest.approx(np.var(X, axis=0))  # the variances are not shrunk
        deltas.append(d)
    assert deltas[0] > deltas[1] > deltas[2]


def test_hrp_splits_by_inverse_variance_and_sums_to_one():
    assert allocation.hrp(np.diag([0.01, 0.04])) == pytest.approx([0.8, 0.2])
    rng = np.random.default_rng(3)
    w = allocation.hrp(np.cov(rng.standard_normal((200, 12)), rowvar=False))
    assert w.sum() == pytest.approx(1) and (w > 0).all()


def test_given_weights_renormalize_over_the_assets_with_history():
    X = np.zeros((10, 2))
    assert allocation.weights("given", X, given=np.array([0.3, 0.1])) == pytest.approx([0.75, 0.25])


def test_portfolio_holds_its_weights_and_shares_a_late_asset_s_weight(fake_sources):
    days, px = random_walk(1500, 0.05, 0.2, seed=9, start="2013-01-01")
    fake_sources["test:LATE"] = Series(id="test:LATE", name="late", currency="RUB", dates=days, values=px, type="index")
    specs = [AssetSpec(id="test:A0", weight=0.5), AssetSpec(id="test:A1", weight=0.3), AssetSpec(id="test:LATE", weight=0.2)]
    b = build(specs)
    p = Params(signal="weights", cost=0.0)
    run = simulate(b, p, sig=signal(b, p))
    early, mid = b.index_of("2012-06-01"), b.index_of("2015-06-01")
    assert run.pos[early] == pytest.approx([0.625, 0.375, 0.0])  # before LATE trades: 0.5 and 0.3 over 0.8
    assert run.pos[mid] == pytest.approx([0.5, 0.3, 0.2])
    assert run.pos[-1] == pytest.approx([0.625, 0.375, 0.0])  # LATE's history has ended: its weight is shared again
    assert run.x[mid] == pytest.approx(float(np.nan_to_num(b.R[mid]) @ np.array([0.5, 0.3, 0.2])))


def test_study_in_portfolio_mode(fake_sources):
    req = {"assets": [{"id": "test:A0", "weight": 0.6}, {"id": "test:A1", "weight": 0.4}], "params": {"signal": "weights"}}
    r = run_study(req)
    assert r["meta"]["mode"] == "portfolio" and r["meta"]["bench"] == "поровну"
    keys = [row["key"] for row in r["allocation"]["rows"]]
    assert "given" in keys and "hrp" in keys and "hold" not in keys
    assert r["scenarios"]["full"] == pytest.approx([0.6, 0.4]) and r["scenarios"]["weights"] == [1.0, 1.0]
    with pytest.raises(ValueError):
        run_study({"assets": [{"id": "test:A0"}], "params": {"signal": "weights"}})


def test_report_as_of_takes_the_latest_published_ifrs_before_the_day():
    reps = [sas.Report("X", "X", "RSBU", "2022", "2023-03-01"), sas.Report("X", "X", "MSFO", "2022", "2023-04-10"),
            sas.Report("X", "X", "MSFO", "2023", "2024-04-01")]
    assert sas.report_as_of(reps, "2023-03-15").standard == "RSBU"
    assert sas.report_as_of(reps, "2023-05-01").standard == "MSFO"
    assert sas.report_as_of(reps, "2024-04-01").period == "2022"  # published that day: not known yet
    assert sas.report_as_of(reps, "2026-01-01") is None  # older than 18 months


def _panel(weeks: int = 140, n: int = 30) -> universe.Panel:
    d0 = date(2014, 1, 3)
    days = [(d0 + timedelta(days=7 * i)).isoformat() for i in range(weeks)]
    r = np.linspace(-0.004, 0.006, n)  # share j earns r_j every week
    R = np.tile(r, (weeks, 1))
    R[0] = np.nan
    P = np.cumprod(np.r_[[np.ones(n)], 1 + R[1:]], axis=0)
    V = np.tile(np.linspace(1e8, 1e7, n), (weeks, 1))
    return universe.Panel(dates=days, tickers=[f"T{j:02d}" for j in range(n)], names={}, P=P, V=V, R=R,
                          D=np.zeros((weeks, n)), covered=np.zeros(n, bool))


def test_factor_lab_arithmetic_on_a_known_panel(monkeypatch):
    monkeypatch.setattr(sas, "reports", lambda: None)
    monkeypatch.setattr(sas, "dividends", lambda: None)
    monkeypatch.setattr(sources, "load", lambda *a, **k: (_ for _ in ()).throw(sources.NotFound("no")))
    p = _panel()
    months, _ = factors.build_months(p, "2015-01-01", top=30)
    m = months[0]
    r = np.linspace(-0.004, 0.006, 30)[m.cols]
    assert m.f["mom"] == pytest.approx((1 + r) ** 48 - 1)  # 12 months but the last: 48 weeks
    assert m.fwd == pytest.approx((1 + r) ** (m.u - m.t) - 1)
    res = factors.evaluate(months, p.dates, p.tickers, "mom", cost=0.0)
    assert res["ic"] == pytest.approx(1.0) and res["ls"] > 0 and res["turnover"] == 0


def test_ic_and_fama_macbeth_find_the_planted_premium():
    rng = np.random.default_rng(5)
    months = []
    for k in range(60):
        a, b = rng.standard_normal(80), rng.standard_normal(80)
        fwd = 0.01 * factors.rank_z(a) + 0.04 * rng.standard_normal(80)  # only `a` pays
        months.append(factors.Month(t=k, u=k + 1, cols=np.arange(80), fwd=fwd, f={"mom": a, "rev": b}))
    dates = [f"20{10 + k // 12:02d}-{k % 12 + 1:02d}-28" for k in range(61)]
    tickers = [str(i) for i in range(80)]
    good = factors.evaluate(months, dates, tickers, "mom", 0.0)
    noise = factors.evaluate(months, dates, tickers, "rev", 0.0)
    assert good["ic_t"] > 5 and abs(noise["ic_t"]) < 3
    fm = factors.fama_macbeth(months, dates, ["mom", "rev"])
    coef = {x["key"]: x for x in fm["rows"]}
    assert coef["mom"]["coef"] == pytest.approx(0.12, rel=0.2) and coef["mom"]["t"] > 5 and abs(coef["rev"]["t"]) < 3
