"""The book on a real account (account.py) on synthetic sleeves: whole contracts, the trend's execution, the tax,
the settings, the wealth around the account in the scenarios."""
import numpy as np
import pytest
from test_book import fake_data

from ram import account, book

ZERO = {"mmf": {"drag": 0.0}, "bond": {"drag": 0.0}, "index": {"drag": 0.0}}
FREE = account.Settings(fee=0.0, fee_fut=0.0, fee_month=0.0, tax=0.0, slip_stock=0.0, slip_fut=0.0, slip_fund=0.0)


def with_futures(seed: int = 4):
    d = fake_data()
    W = len(d.dates)
    rng = np.random.default_rng(seed)
    d.fut_xr = np.vstack([np.full(4, np.nan), rng.normal(0.001, 0.02, (W - 1, 4))])
    d.fut_px = np.cumprod(1 + np.nan_to_num(d.fut_xr), axis=0) * 100
    return d


def fake_market(d: book.Data, value: float) -> account.Market:
    W = len(d.dates)
    return account.Market(col={}, P=np.zeros((W, 0)), live=np.zeros((W, 0), bool), D=np.zeros((W, 0)),
                          lot=np.zeros(0), V=np.full((W, 4), value), margin=np.full(4, 0.1), specs={}, shares={})


TREND = book.Opts(start="2015-01-01", method="weights", budget=(0.0, 0.0, 0.5), limit=0.0)


def test_small_contracts_follow_the_ideal_trend():
    """With contracts worth a rouble and no costs the account is the book: the trend sleeve on money-market capital
    (a hair better: the book pays 0.1% to move money between its sleeves, the free account nothing)."""
    d = with_futures()
    res = book.run(d, TREND)
    sim = account.simulate(d, TREND, fake_market(d, 1.0), FREE, 1e6, res, ZERO)
    assert 0 <= sim["cagr"] - sim["ideal_cagr"] < 1e-3
    assert sim["tracking"] < 2e-3


def test_whole_contracts_miss_the_ideal_when_they_are_too_big():
    d = with_futures()
    res = book.run(d, TREND)
    big = account.simulate(d, TREND, fake_market(d, 5e6), FREE, 3e5, res, ZERO)  # a contract is worth 17 accounts
    small = account.simulate(d, TREND, fake_market(d, 1.0), FREE, 3e5, res, ZERO)
    assert big["tracking"] > 5 * small["tracking"]
    assert big["margin_max"] == 0.0  # nothing could be bought


def test_weekly_execution_ignores_the_daily_rule():
    """By hand once a week the account earns the week-end positions on the markets' moves, not the sleeve's return."""
    d = with_futures()
    res = book.run(d, TREND)
    s = account.Settings(**{**FREE.__dict__, "trend_exec": "weekly"})
    sim = account.simulate(d, TREND, fake_market(d, 1.0), s, 1e6, res, ZERO)
    t0, H = res["t0"], res["held"]
    nav = 1e6
    n = np.round(np.nan_to_num(d.pos["main"][t0]) * H[0][2] * nav)
    for k in range(1, len(H)):  # the same account by hand: the week-end contracts times the next week's moves
        t = t0 + k
        nav = nav * (1 + d.returns["cash"][t]) + float(n @ np.nan_to_num(d.fut_xr[t]))
        n = np.round(np.nan_to_num(d.pos["main"][t]) * H[k][2] * nav)
    assert sim["end"] == pytest.approx(nav, rel=1e-9)
    assert sim["tracking"] > 0.01  # the fake sleeve's return has nothing to do with the fake markets


def test_money_only_pays_the_tax_when_sold():
    d = with_futures()
    o = book.Opts(start="2015-01-01", method="weights", budget=(0.0, 0.0, 0.0), limit=0.0)
    res = book.run(d, o)
    s = account.Settings(**{**FREE.__dict__, "tax": 0.13})
    sim = account.simulate(d, o, fake_market(d, 1.0), s, 1e6, res, ZERO)
    gain = sim["end"] - 1e6
    assert sim["costs"]["income_tax"] == 0.0  # a fund's unit is taxed when it is sold
    assert sim["end_after_tax"] == pytest.approx(sim["end"] - 0.13 * gain)
    ref = account.money_only(d, res["t0"], FREE, 1e6, 0.0)
    assert sim["end"] == pytest.approx(ref["end"], rel=1e-9)


def test_futures_pay_the_tax_every_year():
    """Variation margin is income of the year: the tax leaves in January; before the tax the account is the free one."""
    d = with_futures()
    res = book.run(d, TREND)
    taxed = account.simulate(d, TREND, fake_market(d, 1.0), account.Settings(**{**FREE.__dict__, "tax": 0.13}), 1e6, res,
                             ZERO)
    free = account.simulate(d, TREND, fake_market(d, 1.0), FREE, 1e6, res, ZERO)
    assert taxed["costs"]["income_tax"] > 0
    assert taxed["paid_tax_cagr"] < free["cagr"]
    assert taxed["cagr"] == pytest.approx(free["cagr"], abs=3e-3)  # the shadow of the taxes paid brings it back
    assert taxed["after_tax_cagr"] <= taxed["paid_tax_cagr"] + 1e-12


def test_fees_and_the_tariff_cost_money():
    d = with_futures()
    res = book.run(d, TREND)
    paid = account.simulate(d, TREND, fake_market(d, 1.0), account.Settings(**{**FREE.__dict__, "fee_month": 390.0}),
                            3e5, res, ZERO)
    free = account.simulate(d, TREND, fake_market(d, 1.0), FREE, 3e5, res, ZERO)
    assert paid["costs"]["fixed"] == pytest.approx(390 * 12 / (3e5 * (1 + free["cagr"]) ** 2), rel=0.6)
    assert paid["cagr"] < free["cagr"] - 0.01


def test_settings_validation_and_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(account.events, "_user_dir", lambda: tmp_path)
    with pytest.raises(ValueError):
        account.Settings.from_dict({"money": 100})
    with pytest.raises(ValueError):
        account.Settings.from_dict({"fx": {"XYZ": 10}})
    with pytest.raises(ValueError):
        account.Settings.from_dict({"funds": [{"secid": "bad code!", "units": 1}]})
    s = account.save_settings({"money": "250000", "gold_grams": 50, "funds": [{"secid": "xxxxxx", "units": 3, "payout": 0.1}]})
    assert s.capital == 350_000 and s.funds[0]["secid"] == "XXXXXX"
    assert account.load_settings() == s


def test_wealth_in_the_scenarios(monkeypatch):
    class S:
        def __init__(self, v, name=""):
            self.values, self.dates, self.name = np.array([v]), ["2026-11-25"], name
    prices = {"moex:currency:GLDRUB_TOM": S(10_000.0), "cbr:USD": S(80.0)}
    monkeypatch.setattr(account.sources, "load", lambda sid: prices[sid])
    monkeypatch.setattr(account, "fund_stats", lambda d, code: {"secid": code, "name": "фонд", "price": 1000.0,
                                                                  "last": "2026-11-25", "beta_eq": 0.5, "beta_bd": 0.0,
                                                                  "price_cagr": 0.05})
    s = account.Settings(gold_grams=10, fx={"USD": 1000}, funds=[{"secid": "XXXXXX", "units": 100, "payout": 0.1}])
    scen = [{"label": "девальвация", "kind": "hyp", "loss": 0.2, "moves": [0.5, 0.4, -0.3, -0.1]}]
    w = account.wealth(None, s, 300_000, scen)
    assert w["total"] == pytest.approx(300_000 + 100_000 + 80_000 + 100_000)
    r = w["scenarios"][0]
    assert r["account"] == pytest.approx(-60_000) and r["gold"] == pytest.approx(40_000)
    assert r["fx"] == pytest.approx(40_000) and r["funds"] == pytest.approx(-15_000)
    assert r["total"] == pytest.approx(5_000)
    assert w["funds"][0]["total"] == pytest.approx(0.15)
    assert w["cushion"] == pytest.approx(180_000)
