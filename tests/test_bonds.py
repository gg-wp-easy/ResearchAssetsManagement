"""The bond sleeve from single issues (bonds.py): the money of coupons, amortisations and redemptions, the coupon tax on
the interest earned while held, the kinds of bonds."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from ram import bondmarket as bm
from ram import bonds

DAYS = [(date(2020, 1, 3) + timedelta(days=7 * k)).isoformat() for k in range(6)]


def _market(rows: list[tuple]) -> bm.Market:
    """rows: (week, secid, price, accint, face, matdate)."""
    secids = sorted({r[1] for r in rows})
    rows = sorted(rows, key=lambda r: (secids.index(r[1]), r[0]))
    n = len(rows)
    t = np.array([r[0] for r in rows], np.int32)
    m = bm.Market(dates=DAYS, secids=secids, names={}, boards=["TQOB"], units=["RUB"], t=t,
                  sid=np.array([secids.index(r[1]) for r in rows], np.int32), board=np.zeros(n, np.int16),
                  unit=np.zeros(n, np.int16), price=np.array([r[2] for r in rows], float),
                  accint=np.array([r[3] for r in rows], float), face=np.array([r[4] for r in rows], float),
                  value=np.full(n, 1e7), trades=np.full(n, 10.0), ytm=np.full(n, 0.1), duration=np.full(n, 2.0),
                  mat=np.array([bm._ordinal(r[5]) for r in rows], np.int32), offer=np.zeros(n, np.int32),
                  start=np.zeros(len(DAYS) + 1, np.int64), by_week=np.argsort(t, kind="stable"))
    m.start[1:] = np.cumsum(np.bincount(t, minlength=len(DAYS)))
    return m


def test_a_coupon_is_income_and_its_tax_is_on_the_interest_earned_while_held() -> None:
    # 5 rubles of interest a week; the 30-ruble coupon is paid between weeks 2 and 3 (accrued 20 -> 0 after it)
    acc = [10, 15, 20, 0, 5, 10]
    m = _market([(k, "SU26000RMFS1", 100.0, acc[k], 1000.0, "2030-01-01") for k in range(6)])
    sched = {"SU26000RMFS1": {"coupons": [[(date.fromisoformat(DAYS[2]) + timedelta(days=3)).isoformat(), 30.0, 6.0]],
                              "amort": [["2030-01-01", 1000.0]], "offers": []}}
    zero = np.zeros(6)
    r = bonds.simulate(m, {0: [0]}, sched, zero, 0.0, 0.0)
    v = [1000 + a for a in acc]
    assert np.isnan(r[0])
    assert r[1] == pytest.approx(v[1] / v[0] - 1)
    assert r[3] == pytest.approx((v[3] + 30) / v[2] - 1), "the coupon comes in money, the accrued interest resets"
    assert np.prod(1 + r[1:]) == pytest.approx((1010 + 30) / 1010), "the bond at 1010 again and the coupon in money"
    taxed = bonds.simulate(m, {0: [0]}, sched, zero, 0.13, 0.0)
    # bought at week 0 with 10 of accrued interest, which the coupon pays back untaxed: 30 rubles earned, 13% of them
    earned = (acc[5] - acc[0]) + 30
    assert np.prod(1 + taxed[1:]) * 1010 == pytest.approx(np.prod(1 + r[1:]) * 1010 - 0.13 * earned, rel=1e-9)


def test_an_amortisation_and_the_redemption_come_back_as_money() -> None:
    # face 1000 -> 500 after an amortisation of 500 between weeks 1 and 2; redeemed (500) between weeks 3 and 4
    rows = [(0, "SU46000RMFS1", 100.0, 0.0, 1000.0, DAYS[3]), (1, "SU46000RMFS1", 100.0, 0.0, 1000.0, DAYS[3]),
            (2, "SU46000RMFS1", 100.0, 0.0, 500.0, DAYS[3]), (3, "SU46000RMFS1", 100.0, 0.0, 500.0, DAYS[3])]
    m = _market(rows)
    sched = {"SU46000RMFS1": {"coupons": [], "offers": [],
                              "amort": [[(date.fromisoformat(DAYS[1]) + timedelta(days=2)).isoformat(), 500.0],
                                        [(date.fromisoformat(DAYS[3]) + timedelta(days=2)).isoformat(), 500.0]]}}
    cash = np.full(6, 0.001)
    r = bonds.simulate(m, {0: [0]}, sched, cash, 0.0, 0.0)
    assert r[1] == pytest.approx(0.0)
    assert r[2] == pytest.approx(0.0), "500 in money + 500 of face: no loss"
    assert r[3] == pytest.approx(0.5 * 0.001), "the money earns RUONIA, the rest is in the bond"
    assert r[4] == pytest.approx(0.5 * 0.001, rel=1e-3), "the redemption's money comes during the week: its interest next week"
    assert r[5] == pytest.approx(0.001), "redeemed: all money"


def test_a_rebalance_pays_its_cost_and_holds_equal_shares() -> None:
    rows = [(k, s, 100.0, 0.0, 1000.0, "2030-01-01") for k in range(6) for s in ("SU26000RMFS1", "SU26001RMFS1")]
    m = _market(rows)
    r = bonds.simulate(m, {0: [0], 2: [0, 1]}, {}, np.zeros(6), 0.0, 0.001)
    assert r[1] == pytest.approx(0.0)
    assert r[2] == pytest.approx(-0.001, rel=1e-3), "half the book sold and half bought: one book's worth traded"
    assert r[3] == pytest.approx(0.0), "equal shares of both, nothing borrowed for the cost"


def test_kinds_of_ofz_and_a_floater() -> None:
    assert bonds.ofz_kind("SU26238RMFS4") == "ofz_fixed" and bonds.ofz_kind("SU29006RMFS2") == "ofz_float"
    assert bonds.ofz_kind("SU52005RMFS4") == "ofz_linker" and bonds.ofz_kind("RU000A0JX0J2") is None
    fl = {"coupons": [["2020-01-01", 1, 7.1], ["2020-04-01", 1, 7.4], ["2020-07-01", 1, 6.9], ["2020-10-01", 1, 7.0]]}
    step = {"coupons": [["2020-01-01", 1, 7.0], ["2020-04-01", 1, 7.0], ["2020-07-01", 1, 8.0], ["2020-10-01", 1, 8.0]]}
    assert bonds.floater(fl) and not bonds.floater(step) and not bonds.floater(None)


def test_a_mix_gives_the_share_of_a_kind_not_started_to_the_others() -> None:
    a, b = np.array([np.nan, 0.01, 0.01]), np.array([np.nan, np.nan, 0.03])
    out = bonds.blend({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
    assert np.isnan(out[0]) and out[1] == pytest.approx(0.01) and out[2] == pytest.approx(0.02)


def test_the_curve_between_its_terms() -> None:
    pts = [[1.0, 0.10], [2.0, 0.12], [5.0, 0.15]]
    assert bm.curve_yield(pts, 1.5) == pytest.approx(0.11)
    assert bm.curve_yield(pts, 0.5) == 0.10 and bm.curve_yield(pts, 9) == 0.15 and bm.curve_yield([], 1) is None


def test_life_runs_to_the_schedules_offer_or_coupon_reset() -> None:
    # ISS's history has no offer date (before ~2019): the schedule's offer, or the coupon rate's change, ends the life
    rows = [(k, s, 100.0, 0.0, 1000.0, "2030-01-01") for k in range(6) for s in ("RU000A0OFFER", "RU000A0RESET")]
    m = _market(rows)
    d = bonds.Rows(traded=np.zeros(len(m.t)), value4=np.zeros(len(m.t)), life=np.full(len(m.t), 10.0),
                   spread=np.zeros(len(m.t)), issuer=np.zeros(len(m.t), np.int32), issuers=["x"],
                   defaulted_from=np.array([1 << 30]), order_ok=np.ones(len(m.t), bool))
    sched = {"RU000A0OFFER": {"coupons": [], "amort": [], "offers": [["2020-03-01", "Оферта"], ["2020-01-20", "Оферта (отменена)"]]},
             "RU000A0RESET": {"coupons": [[f"{y}-{md}", 60, 12.0] for y in (2017, 2018, 2019) for md in ("02-01", "08-01")]
                              + [["2020-02-01", 60, 12.0], ["2020-08-01", 0.05, 0.01]], "amort": [], "offers": []}}
    bonds.apply_offers(m, d, sched)
    off, res = m.col("RU000A0OFFER"), m.col("RU000A0RESET")
    day0 = date.fromisoformat(DAYS[0])
    assert d.life[m.at(off, 0)] == pytest.approx((date(2020, 3, 1) - day0).days / 365.25), "a cancelled offer does not count"
    assert d.life[m.at(res, 0)] == pytest.approx((date(2020, 2, 1) - day0).days / 365.25), "12% then 0.01%: sold before"
