"""The whole capital: the account's book of sleeves, physical gold, currency (cash and currency bonds) and
real-estate funds as the classes of one portfolio. Plans for the classes' shares, each tested month by month on what was
known at the time; the book's scenarios on the whole capital; today's moves by hand.

Classes (weekly returns in roubles on the book's weeks, before taxes):
* book   - the book of sleeves on the account (book.run with the account's options); before its start, its first
           decision's weights on the sleeves' returns (known at that date; only for the covariance of the first months);
* gold   - gold in roubles, MOEX's GLDRUB_TOM (from October 2013): bars and the exchange's gold move alike;
* fx     - currency bonds in yuan and dollars in equal halves (bonds.py, from 2022; before them the cash of both
           currencies at the Bank of Russia's rate): the currency a plan adds is bought on the account as bonds;
* realty - the user's real-estate funds: the unit's exchange price plus the payout given in the settings.

Plans - the classes' shares of the capital, set at each month-end, traded when a class drifts BAND away from them
(COST a side: the account adds or trims exchange gold and currency bonds; bars and cash are not traded by a plan):
* book   - everything in the account's book;
* now    - today's shares of the user's capital, kept (the currency as the cash held);
* risk   - equal risk budgets of the classes with a year of history (book.budget_weights on the Ledoit-Wolf covariance
           of 156 weeks over cash);
* regime - the risk budgets by the Bank of Russia's regime (bondpolicy.regimes), set in advance, not fitted: while the
           rate goes up the rouble book earns a high real rate, while it is cut the rouble tends to weaken and gold and
           currency get more.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

import numpy as np

from . import account, bonds, book, sources
from . import bondpolicy as bp
from .allocation import shrunk_cov
from .assets import ffill_on

CLASSES = [("book", "счёт: портфель из блоков"), ("gold", "золото"), ("fx", "валюта"), ("realty", "фонды недвижимости")]
CLASS_TITLES = dict(CLASSES)
PLANS = [("book", "Всё в портфеле из блоков"), ("now", "Доли сегодня"), ("risk", "Риск поровну"),
         ("regime", "Риск по режиму ЦБ")]
PLAN_TITLES = dict(PLANS)
MAIN_PLAN = "risk"  # no view of the regime by default; the page keeps the plan the user picks
REGIME_BUDGET = {  # set before any test: the rouble book's share of the risk by the Bank of Russia's regime
    "tight": {"book": 0.6, "gold": 0.2, "fx": 0.2},
    "hold": {"book": 1 / 3, "gold": 1 / 3, "fx": 1 / 3},
    "ease": {"book": 0.2, "gold": 0.4, "fx": 0.4},
}
REALTY_BUDGET = 0.2  # of the risk, when real-estate funds are held; the other classes share the rest in their proportions
BAND = 0.05
COST = 0.002
FX_MIX = {"fx_cny": 0.5, "fx_usd": 0.5}
CASH_MIX = {"cash_cny": 0.5, "cash_usd": 0.5}
CURRENCY_FROM = "2022-10-01"  # the yuan bonds' first month: the currency table compares the four on the same weeks
GOLD = "moex:currency:GLDRUB_TOM"
MARKET_KEYS = ["cny", "gold", "mcftr", "ofz"]  # book.MARKETS: the scenarios' coordinates


def _weekly(sid: str, days: list[str]) -> tuple[np.ndarray, float, str]:
    s = sources.load(sid)
    v = ffill_on(s.dates, s.values, days)
    return np.r_[np.nan, v[1:] / v[:-1] - 1], float(s.values[-1]), s.dates[-1]


def holdings(d: book.Data, s: account.Settings, notes: list[str]) -> dict:
    """Today's value of every class of the user's capital and its weekly returns where they differ from the plans'
    (the currency held as cash, the funds held)."""
    items = [{"cls": "book", "label": "счёт (деньги на бумаги и на фьючерсы)", "value": s.capital, "sale": s.capital}]
    if s.gold_grams > 0:
        _, px, day = _weekly(GOLD, d.dates)
        v = s.gold_grams * px
        items.append({"cls": "gold", "label": "физическое золото", "value": v, "sale": v * (1 - s.gold_haircut),
                      "detail": f"{s.gold_grams:g} г по {px:,.0f} ₽ ({day})"})
    cash_r, cash_v = [], []
    for code, amount in s.fx.items():
        if amount <= 0:
            continue
        r, rate, day = _weekly(f"cbr:{code}", d.dates)
        v = amount * rate
        cash_r.append(r)
        cash_v.append(v)
        items.append({"cls": "fx", "label": f"наличные {code}", "value": v, "sale": v * (1 - s.fx_haircut),
                      "detail": f"{amount:,.0f} {code} по курсу ЦБ {rate:,.4f} ({day})"})
    fund_r, fund_v, betas = [], [], []
    for f in s.funds:
        try:
            st = account.fund_stats(d, f["secid"])
            r, px, day = _weekly(f"moex:shares:{f['secid']}", d.dates)
        except Exception as e:  # noqa: BLE001 - not on the exchange
            notes.append(f"{f['secid']}: цена пая не загрузилась ({e})")
            continue
        v = f["units"] * px
        fund_r.append(r + f["payout"] / book.WEEKS)
        fund_v.append(v)
        betas.append((st["beta_eq"], st["beta_bd"]))
        items.append({"cls": "realty", "label": st["name"], "value": v, "sale": v, "code": f["secid"],
                      "detail": f"{f['units']:g} паёв по {px:,.0f} ₽ ({day}), выплаты {f['payout']:.1%} в год"})
    total = sum(i["value"] for i in items)
    for i in items:
        i["share"] = i["value"] / total if total else 0.0
    by = {c: sum(i["value"] for i in items if i["cls"] == c) for c, _ in CLASSES}
    out = {"items": items, "total": total, "by": by, "shares": {c: v / total if total else 0.0 for c, v in by.items()}}
    if cash_v:
        out["fx_cash"] = _value_blend(cash_r, cash_v)
    if fund_v:
        out["realty"] = _value_blend(fund_r, fund_v)
        w = np.array(fund_v) / sum(fund_v)
        out["realty_betas"] = (float(w @ [b[0] for b in betas]), float(w @ [b[1] for b in betas]))
    return out


def _value_blend(rs: list[np.ndarray], vs: list[float]) -> np.ndarray:
    return bonds.blend({str(i): r for i, r in enumerate(rs)}, {str(i): v for i, v in enumerate(vs)})


def class_returns(d: book.Data, o: book.Opts, res: dict, hold: dict, notes: list[str]) -> dict[str, np.ndarray]:
    W = len(d.dates)
    t0 = res["t0"]
    x = np.full(W, np.nan)
    x[t0 + 1:] = res["x"]
    bk = book.assemble(d, o)  # before its start: the first decision's weights on its sleeves (for the covariance only)
    first = np.asarray(res["held"][0])
    used = first > 1e-9
    before = bk.R[:t0 + 1]
    x[:t0 + 1] = np.where(np.isfinite(before[:, used]).all(axis=1), np.nan_to_num(before) @ first, np.nan)
    out = {"book": x, "gold": _weekly(GOLD, d.dates)[0]}
    book.bond_sleeve(d)
    fx_bonds = bonds.blend({k: d.returns[f"fx:{k}"] for k in FX_MIX}, FX_MIX)
    cash = bonds.blend({k: d.returns[f"fx:{k}"] for k in CASH_MIX}, CASH_MIX)
    out["fx"] = np.where(np.isfinite(fx_bonds), fx_bonds, cash)
    if "realty" in hold:
        out["realty"] = hold["realty"]
    return out


def budgets(keys: list[str], regime: str | None) -> np.ndarray:
    """The risk budget of each class: equal (regime None) or the regime's; real-estate funds REALTY_BUDGET."""
    base = REGIME_BUDGET[regime] if regime else {k: 1.0 for k in keys if k != "realty"}
    rest = [k for k in keys if k != "realty"]
    s = sum(base.get(k, 0.0) for k in rest)
    share = 1 - REALTY_BUDGET if "realty" in keys else 1.0
    return np.array([REALTY_BUDGET if k == "realty" else share * base.get(k, 0.0) / s for k in keys])


def alive(R: np.ndarray, t: int) -> np.ndarray:
    """The classes that traded over the last four weeks."""
    return np.isfinite(R[max(0, t - 3):t + 1]).all(axis=0)


def risk_target(R: np.ndarray, cash: np.ndarray, t: int, b: np.ndarray) -> np.ndarray | None:
    """Shares with risk contributions equal to the budget b, on the window up to week t; the classes without a year of
    it are left out (None when fewer than two are left)."""
    lo = max(1, t - book.WINDOW + 1)
    X = R[lo:t + 1] - np.nan_to_num(cash[lo:t + 1])[:, None]
    ok = (np.isfinite(X).sum(axis=0) >= book.MIN_WEEKS) & (b > 0) & alive(R, t)
    if ok.sum() < 2:
        return None
    Xo = X[:, ok]
    Xo = Xo[np.isfinite(Xo).all(axis=1)]
    cov, _ = shrunk_cov(Xo)
    w = np.zeros(len(b))
    w[ok] = book.budget_weights(cov, b[ok])
    return w


def fixed_target(R: np.ndarray, t: int, w: np.ndarray) -> np.ndarray:
    """The given shares; a class not trading yet gives its share to the others."""
    w = np.where(alive(R, t), w, 0.0)
    return w / w.sum() if w.sum() > 0 else w


def simulate(R: np.ndarray, ends: set[int], t0: int, target) -> tuple[np.ndarray, dict[int, np.ndarray], int]:
    """Weekly return of the plan from week t0: the month's target (target(t)) where a class drifted BAND away from it,
    COST a side of the share moved; (returns, {month-end: target}, the number of trades)."""
    W, n = R.shape
    x = np.full(W, np.nan)
    targets: dict[int, np.ndarray] = {}
    h = np.zeros(n)
    pending, trades = 0.0, 0
    for t in range(t0, W):
        if t > t0:
            r = np.nan_to_num(R[t])
            x[t] = float(h @ r) - pending
            h = h * (1 + r)
            h = h / h.sum()
        pending = 0.0
        if t in ends or t == t0:
            want = target(t)
            targets[t] = want
            if t == t0:
                h = want
            elif np.abs(want - h).max() > BAND:
                pending = COST * float(np.abs(want - h).sum())
                h = want
                trades += 1
    return x, targets, trades


def exposures(d: book.Data, o: book.Opts, res: dict, keys: list[str], hold: dict) -> np.ndarray:
    """classes x 4: each class's exposure to the four markets of the scenarios (yuan, gold in roubles, MCFTR, OFZ) per
    rouble of it today. The book: its shares' beta to MCFTR, its bonds' beta to the OFZ and the trend's positions (the
    futures of yuan and gold count as currency and gold); gold - gold; the currency - the yuan; the funds - their betas."""
    bk = book.assemble(d, o)
    last = next(r for r in reversed(res["log"]) if r["kind"] == "rebalance")
    b_eq, b_bd = last["betas"]
    w = np.asarray(res["held"][-1])
    pos = np.asarray(bk.pos[len(d.dates) - 1])
    rows = {"book": w[2] * pos + np.array([0.0, 0.0, b_eq * w[0], b_bd * w[1]]),
            "gold": np.array([0.0, 1.0, 0.0, 0.0]), "fx": np.array([1.0, 0.0, 0.0, 0.0])}
    if "realty" in keys:
        be, bb = hold.get("realty_betas", account.FUND_BETA_FALLBACK)
        rows["realty"] = np.array([0.0, 0.0, be, bb])
    return np.vstack([rows[k] for k in keys])


def scenario_moves(d: book.Data, keys: list[str], E: np.ndarray):
    """(the scenarios known today, S x classes: the return of each class in each move vector) - linear in the four
    markets by the exposures E, as the book's own cap sees them."""
    scen = book.Scenarios(d, "9999")
    return scen, scen.V @ E.T


def worst(scen: book.Scenarios, M: np.ndarray, w: np.ndarray, keys: list[str], most: int = 6) -> list[dict]:
    loss = -(M * w[None, :])
    total = loss.sum(axis=1)
    rows = []
    for g, s in enumerate(scen.items):
        sel = np.flatnonzero(scen.group == g)
        k = sel[int(np.argmax(total[sel]))]
        rows.append({"label": s["label"], "kind": s["kind"], "to": s["to"], "loss": float(total[k]),
                     "classes": dict(zip(keys, loss[k].tolist())), "moves": scen.V[k].tolist()})
    rows.sort(key=lambda r: -r["loss"])
    return rows[:most]


def actions(w: dict[str, float], hold: dict, total: float, fx_issues: list[dict], haircut: float = 0.05) -> list[dict]:
    """What to do by hand for the plan's shares: the account buys exchange gold and currency bonds for the part the
    bars and the cash do not cover; what is above the plan outside the account is the user's to sell or keep."""
    out = []
    have = hold["by"]
    acc = have["book"]
    for c in ("gold", "fx", "realty"):
        want = w.get(c, 0.0) * total
        diff = want - have.get(c, 0.0)
        if abs(diff) < 0.01 * total:
            continue
        if c == "gold":
            text = (f"купить на счёте биржевое золото (GLDRUB_TOM) на {diff:,.0f} ₽" if diff > 0 else
                    f"золота больше плана на {-diff:,.0f} ₽: продажа слитков стоит скидки банка (~{haircut * -diff:,.0f} ₽) — "
                    "не докупать и новые деньги класть на счёт")
        elif c == "fx":
            names = ", ".join(f"{b['name']} ({(b['ytm'] or 0):.1%})" for b in fx_issues[:3])
            text = (f"купить на счёте валютных облигаций на {diff:,.0f} ₽" + (f": например, {names}" if names else "")
                    if diff > 0 else f"наличной валюты больше плана на {-diff:,.0f} ₽: обмен в банке с потерей на курсе — "
                                     "решай сам, план её не трогает")
        else:
            text = (f"фондов недвижимости меньше плана на {diff:,.0f} ₽" if diff > 0 else
                    f"фондов недвижимости больше плана на {-diff:,.0f} ₽")
        out.append({"cls": c, "rub": diff, "text": text})
    on_account = sum(max(0.0, a["rub"]) for a in out if a["cls"] in ("gold", "fx"))
    out.append({"cls": "book", "rub": acc - on_account,
                "text": f"портфелю из блоков на счёте остаётся {acc - on_account:,.0f} ₽ из {acc:,.0f} ₽"
                        + (" — на покупки не хватает денег счёта" if on_account > acc else "")})
    return out


@dataclass
class Context:
    """The classes' returns and today's holdings: what every plan's target needs."""
    keys: list[str]
    R: np.ndarray  # W x classes
    cash: np.ndarray
    hold: dict
    regime: list[str]
    key: np.ndarray
    notes: list[str]

    def target(self, plan: str, t: int) -> np.ndarray:
        only_book = np.array([1.0 if k == "book" else 0.0 for k in self.keys])
        if plan == "book":
            return fixed_target(self.R, t, only_book)
        if plan == "now":
            return fixed_target(self.R, t, np.array([self.hold["shares"].get(k, 0.0) for k in self.keys]))
        b = budgets(self.keys, None if plan == "risk" else self.regime[t])
        w = risk_target(self.R, self.cash, t, b)
        return w if w is not None else fixed_target(self.R, t, only_book)

    def today(self, plan: str) -> dict[str, float]:
        return dict(zip(self.keys, self.target(plan, len(self.R) - 1).tolist()))


def context(d: book.Data, o: book.Opts, res: dict, s: account.Settings) -> Context:
    notes: list[str] = []
    hold = holdings(d, s, notes)
    R0 = class_returns(d, o, res, hold, notes)
    keys = [k for k, _ in CLASSES if k in R0]
    try:
        key = bonds.raw_key_rate(d.dates)
    except Exception as e:  # noqa: BLE001
        notes.append(f"ключевая ставка не загрузилась ({e}): режим ЦБ везде «пауза»")
        key = np.full(len(d.dates), np.nan)
    return Context(keys=keys, R=np.column_stack([R0[k] for k in keys]), cash=d.returns["cash"], hold=hold,
                   regime=bp.regimes(d.dates, key), key=key, notes=notes)


def report(req: dict) -> dict:
    """Every plan since the book's start, its yearly returns and growth; today: the capital's classes, each plan's
    shares, the worst scenarios on the whole capital, the moves by hand; the currency held as cash or as bonds."""
    t_start = time.time()
    o = book.Opts.from_dict(req.get("opts") or {"bonds": "own"})
    s = account.Settings.from_dict({**asdict(account.load_settings()), **(req.get("settings") or {})})
    d = book.data(o.cost)
    res = book.run(d, o, log=True)
    ctx = context(d, o, res, s)
    keys, R, cash, hold, notes, regime, key = ctx.keys, ctx.R, ctx.cash, ctx.hold, ctx.notes, ctx.regime, ctx.key
    W = len(d.dates)
    t0 = res["t0"]
    ends = set(d.ends)
    now_w = np.array([hold["shares"].get(k, 0.0) for k in keys])
    plan_target = ctx.target

    plans = [p for p, _ in PLANS if p != "now" or (now_w[0] < 1 - 1e-9)]
    Rn = R.copy()
    if "fx_cash" in hold:  # today's shares: the currency as the cash held
        Rn[:, keys.index("fx")] = np.where(np.isfinite(hold["fx_cash"]), hold["fx_cash"], R[:, keys.index("fx")])
    E = exposures(d, o, res, keys, hold)
    scen, M = scenario_moves(d, keys, E)
    days = d.dates[t0 + 1:]
    rows, curves_x, today_w = [], {}, {}
    for p in plans:
        RR = Rn if p == "now" else R
        x, targets, trades = simulate(RR, ends, t0, lambda t, p=p: plan_target(p, t))
        xs = x[t0 + 1:]
        curves_x[p] = xs
        w_today = plan_target(p, W - 1)
        today_w[p] = w_today
        mean_w = np.mean(np.array(list(targets.values())), axis=0)
        sc = worst(scen, M, w_today, keys)
        rows.append({"key": p, "title": PLAN_TITLES[p], "stats": book.stats(xs, cash[t0 + 1:], days),
                     "trades_year": trades / (len(xs) / book.WEEKS), "mean": dict(zip(keys, mean_w.tolist())),
                     "today": dict(zip(keys, w_today.tolist())), "worst": sc,
                     "exposure": dict(zip(MARKET_KEYS, (w_today @ E).tolist())),
                     "worst_loss": sc[0]["loss"] if sc else 0.0})
    for k in keys:  # every class alone, on the same weeks
        xs = R[t0 + 1:, keys.index(k)]
        if np.isfinite(xs).sum() > 10:
            curves_x[f"class:{k}"] = xs
    idx = book.thin_idx(len(days))
    curves = {}
    for k, xs in curves_x.items():
        grow = np.cumprod(1 + np.nan_to_num(xs))
        first = int(np.flatnonzero(np.isfinite(xs))[0]) if np.isfinite(xs).any() else len(xs)
        curves[k] = [None if i < first else float(grow[i] / grow[first]) for i in idx]
    classes = []
    for k in keys:
        xs = R[t0 + 1:, keys.index(k)]
        ok = np.flatnonzero(np.isfinite(xs))
        classes.append({"key": k, "title": CLASS_TITLES[k], "from": days[int(ok[0])] if len(ok) else None,
                        "stats": book.stats(xs, cash[t0 + 1:], days) if len(ok) > 10 else {}})
    total = hold["total"]
    today_fx = (d.bond_policy or {}).get("today", {})
    fx_issues = sorted(today_fx.get("fx_cny", []) + today_fx.get("fx_usd", []), key=lambda b: -(b.get("value4") or 0))
    g = regime[W - 1]
    since = W - 1
    while since > 0 and regime[since - 1] == g:
        since -= 1
    return {
        "date": d.dates[-1], "start": days[0], "keys": keys, "titles": CLASS_TITLES, "plans": rows,
        "main": s.capital_plan if s.capital_plan in plans else MAIN_PLAN,
        "classes": classes, "years": book.years_table(days, curves_x),
        "curves": {"dates": [days[i] for i in idx], "series": curves},
        "holdings": hold["items"], "total": total, "shares": hold["shares"],
        "actions": {p: actions(dict(zip(keys, today_w[p].tolist())), hold, total, fx_issues, s.gold_haircut) for p in plans},
        "markets": dict(zip(MARKET_KEYS, book.MARKETS)),
        "regime": {"regime": g, "title": bp.REGIME_TITLES[g], "since": d.dates[since],
                   "key": None if not math.isfinite(key[-1]) else float(key[-1]),
                   "budget": dict(zip(keys, budgets(keys, g).tolist()))},
        "budgets": {r: dict(zip(keys, budgets(keys, r).tolist())) for r in REGIME_BUDGET},
        "currency": currency(d), "fx_issues": fx_issues[:12], "limit": o.limit, "opts": o.as_dict(),
        "notes": notes + [
            ("доходности до налогов: у слитков налога нет после трёх лет владения, у валютных облигаций налог берут и с "
             "купонов, и с роста курса при продаже"),
            "наличная валюта и валютные облигации в сценариях движутся как юань (единственная валюта рынков бота)",
        ],
        "params": {"band": BAND, "cost": COST, "fx_mix": FX_MIX, "realty_budget": REALTY_BUDGET,
                   "window": book.WINDOW, "min_weeks": book.MIN_WEEKS},
        "elapsed": time.time() - t_start,
    }


FX_PLAN_ISSUES = 6  # currency bonds in the account's plan: every one is an order placed by hand
GOLD_CODE, GOLD_NAME = "GLDRUB_TOM", "Золото на бирже (грамм)"  # MOEX's currency market: a lot is one gram


def fx_choice(today: dict[str, list[dict]], amount: float, rates: dict[str, float],
              most: int = FX_PLAN_ISSUES) -> list[dict]:
    """The currency bonds for `amount` roubles, FX_MIX by currency: in each the kind's own order (the most traded),
    as many issues (up to most / 2) as leave at least two bonds of each - a dollar bond of a 1000-dollar face costs
    ~80 000 roubles; with less money fewer issues of a smaller face, at the least the cheapest one."""
    out = []
    for kind, share in FX_MIX.items():
        items = today.get(kind, [])
        if not items:
            continue
        rate = rates.get(bonds.FX_UNITS[kind], 1.0)
        priced = [(b, (b["price"] / 100 * b["face"] + b["accint"]) * rate) for b in items]
        budget = amount * share
        chosen: list[dict] = []
        for k in range(max(1, most // 2), 0, -1):
            fit = [b for b, p in priced if budget / k >= 2 * p]
            if len(fit) >= k:
                chosen = fit[:k]
                break
        if not chosen:
            chosen = [min(priced, key=lambda bp_: bp_[1])[0]]
        out += [{**b, "kind": kind, "weight": share / len(chosen)} for b in chosen]
    total = sum(b["weight"] for b in out)
    return [{**b, "weight": b["weight"] / total} for b in out] if total else out


def plan_section(d: book.Data, o: book.Opts, res: dict, s: account.Settings) -> dict:
    """The whole capital's part of today's plan (account.plan, the bot's plan version 3): the shares of the plan the
    settings name, the wealth outside the broker accounts in roubles, the Bank of Russia's rates, and the instruments
    the account holds for it - the exchange gold and up to FX_PLAN_ISSUES currency bonds (half in yuan, half in
    dollars; an issue an exchange event takes out is replaced), each with its weight within its class."""
    ctx = context(d, o, res, s)
    shares = ctx.today(s.capital_plan)
    rates = {}
    for code in ("CNY", "USD"):
        c = sources.load(f"cbr:{code}")
        rates[code] = float(c.values[-1])
    g = sources.load(GOLD)
    rows = [{"kind": "gold", "code": GOLD_CODE, "name": GOLD_NAME, "weight": 1.0, "lot": 1, "price": float(g.values[-1]),
             "currency": "RUB", "price_date": g.dates[-1]}]
    outside = {c: float(v) for c, v in ctx.hold["by"].items() if c != "book"}
    amount = account.on_account({"shares": shares, "outside": outside}, s.capital)["fx"]  # on the settings' capital
    today = account.without_exits({k: (d.bond_policy or {}).get("today", {}).get(k, []) for k in FX_MIX})
    for b in fx_choice(today, amount, rates):
        rows.append({"kind": "fx_bond", "code": b["secid"], "name": b["name"], "weight": b["weight"], "lot": 1,
                     "price": b["price"] / 100 * b["face"], "accint": b["accint"], "face": b["face"],
                     "price_pct": b["price"], "currency": bonds.FX_UNITS[b["kind"]], "bond_kind": b["kind"],
                     "ytm": b["ytm"], "duration": b["duration"]})
    W = len(d.dates)
    g_ = ctx.regime[W - 1]
    return {"plan": s.capital_plan, "title": PLAN_TITLES[s.capital_plan], "shares": shares,
            "outside": outside, "rates": rates, "rows": rows,
            "regime": {"regime": g_, "title": bp.REGIME_TITLES[g_],
                       "key": None if not math.isfinite(ctx.key[-1]) else float(ctx.key[-1])}}


def currency(d: book.Data) -> dict:
    """The currency as cash or as bonds, in yuan and in dollars, on the same weeks (from the yuan bonds' start)."""
    days = d.dates
    i0 = next(i for i, x in enumerate(days) if x >= CURRENCY_FROM)
    cash = d.returns["cash"][i0:]
    rows = []
    for k, title in bonds.FX_KINDS + bonds.FX_CASH:
        x = d.returns.get(f"fx:{k}")
        if x is None:
            continue
        xt = d.returns.get(f"fx:{k}:tax")
        rows.append({"key": k, "title": title, "stats": book.stats(x[i0:], cash, days[i0:]),
                     "tax": book.stats(xt[i0:], cash, days[i0:]) if xt is not None else None})
    return {"from": days[i0], "rows": rows}
