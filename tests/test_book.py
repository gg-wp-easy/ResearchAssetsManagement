"""The book of sleeves (book.py) on synthetic sleeves: the risk budget, the scenario cap, point in time."""
from datetime import date, timedelta

import numpy as np
import pytest

from ram import book, factors


def test_budget_weights_meet_the_budget():
    rng = np.random.default_rng(1)
    for _ in range(20):
        A = rng.normal(size=(3, 3))
        cov = A @ A.T + np.diag(rng.uniform(0.01, 0.1, 3))
        b = rng.uniform(0.1, 1.0, 3)
        w = book.budget_weights(cov, b)
        assert (w > 0).all() and abs(w.sum() - 1) < 1e-9
        assert np.allclose(book.contributions(cov, w), b / b.sum(), atol=1e-6)


def test_budget_weights_with_a_hedge():
    """A negatively correlated sleeve still gets its share of the risk (Spinu's problem is convex for any covariance)."""
    cov = np.array([[0.04, 0.01, -0.02], [0.01, 0.01, -0.005], [-0.02, -0.005, 0.03]])
    w = book.budget_weights(cov, np.ones(3))
    assert np.allclose(book.contributions(cov, w), 1 / 3, atol=1e-6)


def test_cap_meets_the_limit_and_cuts_the_culprit():
    rng = np.random.default_rng(2)
    w = np.array([0.3, 0.4, 0.3])
    moves = np.column_stack([rng.uniform(-0.6, 0.1, 50), rng.uniform(-0.1, 0.05, 50), rng.uniform(-1.5, 0.5, 50)])
    c = book.cap(w, moves, np.ones(3), 0.2)
    assert (-(moves * (w * c)[None, :]).sum(axis=1)).max() <= 0.2 + 1e-7
    assert ((c >= 0) & (c <= 1)).all()
    # the trend loses most in the worst vectors: it is cut most, the bonds least
    assert c[2] < c[0] < c[1] + 1e-9


def test_cap_keeps_a_hedge():
    w = np.array([0.5, 0.0, 0.5])
    moves = np.array([[-0.6, 0.0, 0.4], [-0.3, 0.0, 0.1]])  # the trend gains when the shares fall
    c = book.cap(w, moves, np.ones(3), 0.05)
    assert c[2] == pytest.approx(1.0)
    assert (-(moves * (w * c)[None, :]).sum(axis=1)).max() <= 0.05 + 1e-7


def test_cap_untouched_when_nothing_breaks_the_limit():
    w = np.array([0.2, 0.3, 0.2])
    moves = np.array([[-0.1, -0.1, -0.1]])
    assert np.allclose(book.cap(w, moves, np.ones(3), 0.25), 1.0)


def fake_data(W: int = 260, seed: int = 3) -> book.Data:
    rng = np.random.default_rng(seed)
    start = date(2014, 1, 3)
    dates = [(start + timedelta(weeks=k)).isoformat() for k in range(W)]
    eq = rng.normal(0.003, 0.03, W)
    bd = 0.3 * eq + rng.normal(0.001, 0.01, W)
    tr = rng.normal(0.004, 0.02, W)
    cash = np.full(W, 0.0015)
    for r in (eq, bd, tr, cash):
        r[0] = np.nan
    pos = np.column_stack([rng.uniform(-1, 1, W), rng.uniform(-1, 1, W), rng.uniform(-1, 1, W), rng.uniform(-2, 2, W)])
    scen = [{"label": label, "kind": "hyp", "to": "", "moves": np.array([m], float)} for label, m in book.BOT_HYPOTHETICAL]
    scen.append({"label": "окно 2016", "kind": "hist", "to": "2016-06-30",
                 "moves": np.array([[0.5, 0.4, -0.5, -0.3], [0.1, 0.1, -0.2, -0.1]])})
    ends = [t for t in factors.month_ends(dates) if t < W - 1]
    return book.Data(dates=dates, ends=ends,
                     returns={"equity:composite": eq, "bonds:ofz": bd, "trend:main": tr, "cash": cash},
                     picks={"composite": {}}, pos={"main": pos}, mkt=np.column_stack([eq, bd]), scenarios=scen,
                     names={}, notes=[], panel_to=dates[-1])


def test_run_respects_the_limit_every_week():
    d = fake_data()
    for limit in (0.10, 0.25):
        res = book.run(d, book.Opts(start="2015-01-01", limit=limit), log=True)
        assert res["worst_after"][1:].max() <= limit + 1e-6
        H = res["held"]
        assert (H >= -1e-12).all() and np.allclose(H.sum(axis=1), 1.0)
        assert any(r["kind"] == "rebalance" for r in res["log"])


def test_no_cap_lets_the_scenario_loss_grow():
    d = fake_data()
    capped = book.run(d, book.Opts(start="2015-01-01", limit=0.10))
    free = book.run(d, book.Opts(start="2015-01-01", limit=0.0))
    assert free["worst_after"].max() > capped["worst_after"].max()


def test_no_look_ahead():
    """Changing the returns and the trend's positions after week k leaves every weight up to k as it was."""
    d = fake_data()
    o = book.Opts(start="2015-01-01")
    a = book.run(d, o)
    k = 180
    e = fake_data()
    for key in e.returns:
        e.returns[key][k + 1:] = np.random.default_rng(9).normal(0, 0.05, len(e.returns[key]) - k - 1)
    e.pos["main"][k + 1:] = 3.0
    b = book.run(e, o)
    t0 = a["t0"]
    assert b["t0"] == t0
    assert np.allclose(a["held"][:k - t0 + 1], b["held"][:k - t0 + 1])


def test_history_counts_only_after_the_window():
    d = fake_data()
    before = book.Scenarios(d, "2016-06-30")
    after = book.Scenarios(d, "2016-07-01")
    assert all(s["label"] != "окно 2016" for s in before.items)
    assert any(s["label"] == "окно 2016" for s in after.items)
    assert len(after.V) == len(before.V) + 2


def test_weights_method_holds_given_shares():
    d = fake_data()
    res = book.run(d, book.Opts(start="2015-01-01", method="weights", budget=(0.3, 0.3, 0.0), limit=0.0))
    t0 = res["t0"]
    first = res["held"][0]
    assert first[:3] == pytest.approx([0.3, 0.3, 0.0]) and first[3] == pytest.approx(0.4)
    assert d.dates[t0] >= "2015-01-01"


def test_opts_validation():
    with pytest.raises(ValueError):
        book.Opts.from_dict({"method": "weights", "budget": [0.6, 0.6, 0.1]})
    with pytest.raises(ValueError):
        book.Opts.from_dict({"equity": "magic"})
    o = book.Opts.from_dict({"budget": {"equity": 1, "bonds": 1, "trend": 2}, "limit": "0.3"})
    assert o.budget == (1.0, 1.0, 2.0) and o.limit == 0.3


def test_top_fifth_and_composite():
    s = np.array([5.0, 1.0, np.nan, 3.0, 4.0, 2.0, 0.0, 6.0, 7.0, 8.0, 9.0])
    top = book.top_fifth(s)
    assert set(top) == {9, 10}
    m = factors.Month(t=0, u=1, cols=np.arange(5), fwd=np.zeros(5),
                      f={"mom": np.array([1.0, 2, 3, 4, 5]), "lowvol": np.array([5.0, 4, 3, 2, 1]),
                         "ep": np.array([np.nan, np.nan, np.nan, np.nan, 1.0])})
    c = book.composite(m)  # E/P is known for a fifth: left out; momentum and low volatility cancel
    assert np.allclose(c, 0.0)
