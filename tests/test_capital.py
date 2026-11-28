"""The whole capital (capital.py) and the currency bonds (bonds.py): the plans' budgets, their trading by the band, the
moves by hand, the accrued interest of a currency bond from its schedule, a currency return in roubles."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from ram import bondmarket as bm
from ram import bonds, capital


def test_the_regime_budgets_and_the_funds_share() -> None:
    keys = ["book", "gold", "fx"]
    assert capital.budgets(keys, None) == pytest.approx([1 / 3] * 3)
    assert capital.budgets(keys, "tight") == pytest.approx([0.6, 0.2, 0.2])
    b = capital.budgets(keys + ["realty"], "ease")
    assert b.sum() == pytest.approx(1.0) and b[3] == pytest.approx(capital.REALTY_BUDGET)
    assert b[1] / b[0] == pytest.approx(2.0), "the regime's proportions kept among the other classes"


def test_a_plan_trades_only_past_the_band_and_pays_for_it() -> None:
    # two classes, the second doubles in week 2: the target 50/50 drifts to 1/3 - 2/3 and is traded back at week 4
    R = np.zeros((7, 2))
    R[2, 1] = 1.0
    x, targets, trades = capital.simulate(R, {4}, 0, lambda t: np.array([0.5, 0.5]))
    assert x[2] == pytest.approx(0.5)
    assert trades == 1 and set(targets) == {0, 4}
    moved = abs(0.5 - 1 / 3) + abs(0.5 - 2 / 3)
    assert x[5] == pytest.approx(-capital.COST * moved), "the cost of the trade comes out of the next week"
    R2 = np.zeros((7, 2))
    R2[2, 1] = 0.1  # 0.5 -> 0.524: inside the band, no trade
    assert capital.simulate(R2, {4}, 0, lambda t: np.array([0.5, 0.5]))[2] == 0


def test_a_class_not_trading_yet_gives_its_share_to_the_others() -> None:
    R = np.array([[0.01, np.nan, 0.0]] * 5)
    assert capital.fixed_target(R, 4, np.array([0.5, 0.3, 0.2])) == pytest.approx([0.5 / 0.7, 0.0, 0.2 / 0.7])


def test_the_moves_by_hand_buy_on_the_account_what_the_bars_and_cash_do_not_cover() -> None:
    hold = {"by": {"book": 300_000.0, "gold": 100_000.0, "fx": 0.0, "realty": 0.0}}
    total = 400_000.0
    out = capital.actions({"book": 0.6, "gold": 0.1, "fx": 0.3}, hold, total, [], haircut=0.05)
    by = {a["cls"]: a for a in out}
    assert by["gold"]["rub"] == pytest.approx(-60_000) and "3,000" in by["gold"]["text"], "the bars' sale costs the haircut"
    assert by["fx"]["rub"] == pytest.approx(120_000)
    assert by["book"]["rub"] == pytest.approx(300_000 - 120_000), "the currency bonds are bought out of the account"


def test_a_currency_bond_accrues_in_its_face_currency_from_the_schedule() -> None:
    days = [(date(2024, 1, 5) + timedelta(days=7 * k)).isoformat() for k in range(4)]
    n = len(days)
    m = bm.Market(dates=days, secids=["RU000A0CNY01"], names={}, boards=["TQCB"], units=["RUB", "CNY"],
                  t=np.arange(n, dtype=np.int32), sid=np.zeros(n, np.int32), board=np.zeros(n, np.int16),
                  unit=np.ones(n, np.int16), price=np.full(n, 100.0), accint=np.full(n, 999.0), face=np.full(n, 1000.0),
                  value=np.full(n, 1e7), trades=np.full(n, 10.0), ytm=np.full(n, 0.08), duration=np.full(n, 1.0),
                  mat=np.zeros(n, np.int32), offer=np.zeros(n, np.int32), start=np.zeros(n + 1, np.int64),
                  by_week=np.arange(n))
    # coupons of 20 yuan on 2023-12-29 and 2024-01-26 (28 days): on 2024-01-12 two weeks of four are accrued
    sched = {"RU000A0CNY01": {"coupons": [["2023-12-29", 20.0, 7.3], ["2024-01-26", 20.0, 7.3]], "amort": [], "offers": []}}
    acc = bonds.fx_accint(m, sched, {1})
    assert acc[1] == pytest.approx(10.0), "ISS's 999 roubles replaced by 10 yuan"
    assert acc[3] == 0.0, "past the last coupon: nothing accrued"


def test_a_currency_return_in_roubles() -> None:
    r = np.array([np.nan, 0.01, 0.0])
    rate = np.array([10.0, 11.0, 11.0])
    out = bonds.to_roubles(r, rate)
    assert np.isnan(out[0]) and out[1] == pytest.approx(1.01 * 1.1 - 1) and out[2] == pytest.approx(0.0)


def test_the_account_buys_the_plans_gold_and_currency_less_what_is_outside() -> None:
    from ram import account
    cap = {"shares": {"book": 0.6, "gold": 0.15, "fx": 0.25}, "outside": {"gold": 100_000.0, "fx": 20_000.0, "realty": 0.0}}
    acc = account.on_account(cap, 400_000)
    assert acc == pytest.approx({"gold": 0.0, "fx": 0.25 * 520_000 - 20_000}), "the bars cover the gold"
    small = account.on_account({"shares": {"gold": 0.5, "fx": 0.5}, "outside": {}}, 100_000)
    assert sum(small.values()) == pytest.approx(100_000), "never more than the account"
    assert account.on_account(None, 100_000) == {"gold": 0.0, "fx": 0.0}


def test_capital_rows_count_a_currency_bond_in_roubles() -> None:
    from ram import account
    cap = {"rates": {"CNY": 12.0}, "rows": [
        {"kind": "gold", "code": "GLDRUB_TOM", "weight": 1.0, "lot": 1, "price": 9600.0, "currency": "RUB"},
        {"kind": "fx_bond", "code": "X", "weight": 1.0, "lot": 1, "price": 990.0, "accint": 10.0, "currency": "CNY"}]}
    rows = {r["code"]: r for r in account.capital_rows(cap, {"gold": 48_000.0, "fx": 60_000.0})}
    assert rows["GLDRUB_TOM"]["lots"] == 5
    assert rows["X"]["price_rub"] == pytest.approx(12_000.0) and rows["X"]["lots"] == 5


def test_currency_bonds_that_leave_two_bonds_each() -> None:
    def b(s: str, face: float) -> dict:
        return {"secid": s, "name": s, "price": 100.0, "face": face, "accint": 0.0, "ytm": 0.08, "duration": 1.0}
    today = {"fx_cny": [b("C1", 1000), b("C2", 1000), b("C3", 1000)], "fx_usd": [b("U1", 1000), b("U2", 100), b("U3", 100)]}
    rates = {"CNY": 12.0, "USD": 80.0}
    small = capital.fx_choice(today, 60_000, rates)  # 30 000 a currency: one yuan bond is 12 000, a $1000 one 80 000
    assert [x["secid"] for x in small] == ["C1", "U2"]
    assert sum(x["weight"] for x in small) == pytest.approx(1.0)
    big = capital.fx_choice(today, 3_000_000, rates)
    assert len(big) == 6 and {x["kind"] for x in big} == {"fx_cny", "fx_usd"}
    assert capital.fx_choice(today, 0.0, rates)[0]["secid"] == "C1", "no money yet: still the cheapest of each"


def test_an_exchange_event_takes_an_issue_out_of_the_plan(monkeypatch) -> None:
    from ram import account, events
    monkeypatch.setattr(events, "check", lambda codes: {"B": {"status": "exclude"}, "C": {"status": "warn"}})
    today = {"corp_fixed": [{"secid": "A"}, {"secid": "B"}, {"secid": "C"}]}
    assert [x["secid"] for x in account.without_exits(today)["corp_fixed"]] == ["A", "C"]
