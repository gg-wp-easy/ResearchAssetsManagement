"""The bond sleeve from single issues, no fund but the money market's (the data: bondmarket.py).

Kinds of bonds, each with its job:

* ofz_short  - fixed-coupon OFZ (ПД, АД) with a duration of 0.5-3 years: near the key rate, little price risk;
* ofz_long   - fixed-coupon OFZ from 5 years: gains when rates fall, loses when they rise;
* ofz_ladder - fixed-coupon OFZ of 0.5-12 years in equal shares: the whole curve;
* ofz_float  - ОФЗ-ПК: the coupon follows RUONIA or the key rate, so a rise of rates costs little;
* ofz_linker - ОФЗ-ИН: the face is indexed to inflation;
* corp_fixed, corp_float - corporate and regional bonds of the safest kind. In the past broker risk is not known, so
  the proxy is what the market showed then: a liquid issue, a G-spread over the КБД in the lower half of the market's
  and below 6%, a price above 85% of the face, an issuer never seen in the defaulted bonds' sector. Today the
  T-Invest broker risk 1 of server-analytic-system's list is required too.

At each month's end every kind is rebuilt: the eligible issues in equal shares (the ones held stay while still
eligible; a corporate kind holds one issue an issuer). Week by week: the price (% of the face x the face) and the
accrued interest from MOEX, the coupons and amortisations from the issue's schedule; the coupon tax on the interest
earned while held (accrual: the accrued interest paid at a purchase lowers the tax, as the tax code has it); the money
of a redemption in RUONIA until the month's end; a trade costs half the spread plus the broker's fee. An issue is
bought with at least half a year to its maturity or offer and sold below a quarter, so no offer is ever presented.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

import numpy as np

from . import bondmarket as bm
from . import bondpolicy as bp
from . import sas, sources
from .assets import carry_rate, ffill_on
from .factors import month_ends

KINDS = [
    ("ofz_short", "ОФЗ с постоянным купоном, 0,5–3 года"),
    ("ofz_long", "ОФЗ с постоянным купоном, от 5 лет"),
    ("ofz_ladder", "Лестница ОФЗ с постоянным купоном, 0,5–12 лет"),
    ("ofz_float", "ОФЗ-ПК, флоатеры"),
    ("ofz_linker", "ОФЗ-ИН, линкеры"),
    ("corp_fixed", "Корпоративные и региональные, постоянный купон, до 3 лет"),
    ("corp_float", "Корпоративные и региональные, флоатеры"),
]
KIND_TITLES = dict(KINDS)
MIXES = [  # (key, title, {kind: share})
    ("near_cash", "Почти деньги: флоатеры и короткие ОФЗ", {"ofz_float": 0.7, "ofz_short": 0.3}),
    ("ladder", "Лестница ОФЗ", {"ofz_ladder": 1.0}),
    ("ofz3", "ОФЗ трёх видов", {"ofz_ladder": 0.5, "ofz_float": 0.25, "ofz_linker": 0.25}),
    ("mixed", "ОФЗ и корпоративные", {"ofz_ladder": 0.3, "ofz_float": 0.15, "ofz_linker": 0.15,
                                      "corp_fixed": 0.25, "corp_float": 0.15}),
]
OFZ_FIXED, OFZ_FLOAT, OFZ_LINKER = ("25", "26", "46", "48"), ("24", "29"), ("52",)
CORP_TYPES = {"corporate_bond", "exchange_bond", "subfederal_bond", "municipal_bond"}
BUY_LIFE, SELL_LIFE = 0.5, 0.25  # years to maturity or the offer
MIN_TRADED_WEEKS, MIN_VALUE = 3, 300_000.0  # of the last 4 weeks; rubles traded a week on average
MIN_PRICE = 85.0
SPREAD_CAP = 0.06
MAX_CORP = 15
MAX_OFZ = 12
COST = {"ofz": 0.001, "corp": 0.002}  # one way: half the spread and the broker's 0.05%
TAX = 0.13
START = "2014-01-31"  # the КБД starts in January 2014: the corporate spreads are measured from it


def ofz_kind(secid: str) -> str | None:
    """ОФЗ by its number: SU<5 digits>RMFS - 25, 26 fixed (ПД), 46, 48 amortised (АД), 24, 29 floating (ПК), 52 indexed
    (ИН)."""
    if not (secid.startswith("SU") and secid[2:7].isdigit()):
        return None
    head = secid[2:4]
    return ("ofz_fixed" if head in OFZ_FIXED else "ofz_float" if head in OFZ_FLOAT
            else "ofz_linker" if head in OFZ_LINKER else None)


def floater(schedule: dict | None) -> bool:
    """A coupon that changes at most payments (a step-up changes a few times, a floater nearly every time)."""
    if not schedule:
        return False
    rates = [c[2] for c in schedule.get("coupons", []) if c[2] is not None]
    if len(rates) < 3:
        return False
    changes = sum(1 for a, b in pairwise(rates) if abs(a - b) > 1e-6)
    return changes >= 0.5 * (len(rates) - 1)


@dataclass
class Rows:
    """The derived columns of the market's long table, row by row."""
    traded: np.ndarray  # weeks with trades among the last 4 (this one included)
    value4: np.ndarray  # rubles traded over the last 4 weeks
    life: np.ndarray  # years to the offer or maturity (inf when unknown)
    spread: np.ndarray  # G-spread over the КБД (NaN without a yield or a curve)
    issuer: np.ndarray  # issuer index
    issuers: list[str]
    defaulted_from: np.ndarray  # per issuer: first week in the defaulted sector (a big number when never)
    order_ok: np.ndarray  # an order-book board that is not the defaulted bonds' or the qualified investors'


def derive(m: bm.Market, meta: dict[str, dict]) -> Rows:
    n = len(m.t)
    traded = (m.trades > 0).astype(np.int32)
    value4 = np.nan_to_num(m.value).copy()
    for j in (1, 2, 3):
        same = np.zeros(n, bool)
        same[j:] = (m.sid[j:] == m.sid[:-j]) & (m.t[j:] - m.t[:-j] <= 3)
        traded[j:] += np.where(same[j:], (m.trades[:-j] > 0).astype(np.int32), 0)
        value4[j:] += np.where(same[j:], np.nan_to_num(m.value[:-j]), 0.0)
    ords = np.array([date.fromisoformat(d).toordinal() for d in m.dates])
    day = ords[m.t]
    horizon = np.where(m.offer > day, m.offer, m.mat)
    life = np.where(horizon > 0, (horizon - day) / 365.25, np.inf)
    titles = bm.boards()
    defaulted = np.array([bm.defaulted_board(titles.get(b, "")) for b in m.boards])
    qualified = np.array([bm.qualified_board(titles.get(b, "")) for b in m.boards])
    order_ok = ~defaulted[m.board] & ~qualified[m.board]
    names = [str((meta.get(s) or {}).get("emitent_id") or s) for s in m.secids]
    issuers = sorted(set(names))
    icol = {x: i for i, x in enumerate(issuers)}
    per_bond = np.array([icol[x] for x in names], np.int32)
    issuer = per_bond[m.sid]
    first = np.full(len(issuers), 1 << 30, np.int64)
    bad = defaulted[m.board]
    np.minimum.at(first, issuer[bad], m.t[bad])
    spread = np.full(n, np.nan)
    for t in range(len(m.dates)):
        rows = bm.cross_section(m, t)
        pts = m.curves[t] if t < len(m.curves) else []
        if not pts:
            continue
        ok = rows[np.isfinite(m.ytm[rows]) & np.isfinite(m.duration[rows])]
        spread[ok] = m.ytm[ok] - np.array([bm.curve_yield(pts, float(x)) for x in m.duration[ok]])
    return Rows(traded=traded, value4=value4, life=life, spread=spread, issuer=issuer, issuers=issuers,
                defaulted_from=first, order_ok=order_ok)


def risk_one() -> set[str] | None:
    """Broker risk 1 of server-analytic-system's T-Invest list (tickers = MOEX secids), None without the list."""
    d = sas.sas_dir()
    path = d / "bonds_data.json" if d else None
    if not path or not path.exists():
        return None
    import json
    try:
        items = json.loads(path.read_text(encoding="utf-8")).get("instruments", [])
    except ValueError:
        return None
    return {str(x.get("ticker")) for x in items if x.get("risk_level") == 1 and x.get("currency") == "rub"}


def classify(m: bm.Market, meta: dict[str, dict], sched: dict[str, dict]) -> list[str | None]:
    """The kind group of every bond: ofz_fixed / ofz_float / ofz_linker / corp_fixed / corp_float / None."""
    out: list[str | None] = []
    for s in m.secids:
        k = ofz_kind(s)
        if k is None and (meta.get(s) or {}).get("type") in CORP_TYPES:
            k = "corp_float" if floater(sched.get(s)) else "corp_fixed"
        out.append(k)
    return out


def _eligible_base(m: bm.Market, d: Rows, rows: np.ndarray, t: int) -> np.ndarray:
    return rows[(m.unit[rows] == m.units.index("RUB")) & d.order_ok[rows] & (d.traded[rows] >= MIN_TRADED_WEEKS)
                & (d.value4[rows] >= 4 * MIN_VALUE) & (m.price[rows] >= MIN_PRICE)]


def resets(schedule: dict) -> set[int]:
    """The payment dates after which a fixed coupon changes (an offer the schedule does not list as one: the issuer
    set a new rate, often near zero for the holders who did not present the bond)."""
    cps = [(bm._ordinal(c[0]), c[2]) for c in schedule.get("coupons", []) if c[2] is not None]
    return {a[0] for a, b in pairwise(cps) if abs(a[1] - b[1]) > 1e-6}


def apply_offers(m: bm.Market, d: Rows, sched: dict[str, dict]) -> None:
    """Life to the schedule's next offer: ISS's history has no offer date before about 2019, and a bond held through
    its offer gets the issuer's new coupon (often near zero) instead of its face back."""
    ords = np.array([date.fromisoformat(x).toordinal() for x in m.dates])
    for s, secid in enumerate(m.secids):
        sc = sched.get(secid) or {}
        offs = {bm._ordinal(o[0]) for o in sc.get("offers", []) if "отмен" not in str(o[1]).lower()}
        if not ofz_kind(secid) and not floater(sc):
            offs |= resets(sc)
        offs = sorted(offs)
        if not offs:
            continue
        lo, hi = np.searchsorted(m.sid, s, "left"), np.searchsorted(m.sid, s, "right")
        if lo == hi:
            continue
        day = ords[m.t[lo:hi]]
        offs_a = np.array(offs + [1 << 30], np.int64)
        nxt = offs_a[np.searchsorted(offs_a, day, side="right")]
        mat = np.where(m.mat[lo:hi] > 0, m.mat[lo:hi], 1 << 30)
        horizon = np.minimum(nxt, mat)
        d.life[lo:hi] = np.where(horizon < (1 << 30), (horizon - day) / 365.25, np.inf)


def coupon_margin(m: bm.Market, sched: dict[str, dict], groups: np.ndarray, key: np.ndarray) -> np.ndarray:
    """A floater's current coupon rate over the key rate, row by row (NaN for the other bonds): the premium the
    issuer pays for its credit - a quoted margin of 1-2 points is the safe issuers'."""
    out = np.full(len(m.t), np.nan)
    ords = np.array([date.fromisoformat(x).toordinal() for x in m.dates])
    for s in np.flatnonzero(groups == "corp_float"):
        cps = [(bm._ordinal(c[0]), c[2]) for c in (sched.get(m.secids[s]) or {}).get("coupons", [])]
        known = [(o, r) for o, r in cps if r is not None]
        if not known:
            continue
        dates_c = np.array([o for o, _ in known], np.int64)
        rates = np.array([r for _, r in known], float) / 100
        lo, hi = np.searchsorted(m.sid, s, "left"), np.searchsorted(m.sid, s, "right")
        day = ords[m.t[lo:hi]]
        i = np.minimum(np.searchsorted(dates_c, day, side="right"), len(rates) - 1)  # the coupon being accrued
        out[lo:hi] = rates[i] - key[m.t[lo:hi]]
    return out


FLOAT_MARGIN = 0.025


def corp_quality(m: bm.Market, d: Rows, rows: np.ndarray, t: int, risk: set[str] | None, groups: np.ndarray,
                 margin: np.ndarray, loose: bool = False) -> np.ndarray:
    """The safe corporates of week t (rows), the issuer never in default so far. Fixed coupons: a sane yield and a
    G-spread between -1% and the lower half of the market's (at most SPREAD_CAP). Floaters: a price of at least 95%
    and a coupon at most FLOAT_MARGIN over the key rate. Today also broker risk 1 (`risk`).
    `loose` - what a held bond must keep to stay: a spread up to 1.5 medians or the median + 1 point (SPREAD_CAP + 2
    points at most), a floater's price from 90% and margin up to one point more. Without the gap a third of the
    issues changed every month and the trades cost 1.6% a year."""
    rows = rows[d.defaulted_from[d.issuer[rows]] > t]
    g = groups[m.sid[rows]]
    fx = rows[(g == "corp_fixed") & np.isfinite(d.spread[rows]) & (m.ytm[rows] > 0) & (m.ytm[rows] < 0.5)
              & (d.spread[rows] >= (-0.02 if loose else -0.01))]
    if len(fx):
        med = float(np.median(d.spread[fx]))
        cut = min(max(1.5 * med, med + 0.01), SPREAD_CAP + 0.02) if loose else min(med, SPREAD_CAP)
        fx = fx[d.spread[fx] <= cut]
    fl = rows[(g == "corp_float") & (m.price[rows] >= (90 if loose else 95))
              & (margin[rows] <= FLOAT_MARGIN + (0.01 if loose else 0.0))]
    out = np.concatenate([fx, fl])
    if risk is not None:
        out = out[np.array([m.secids[s] in risk for s in m.sid[out]], bool)]
    return out


def key_rate(days: list[str], notes: list[str]) -> np.ndarray:
    """The key rate on each day; RUONIA before 2013-09-13, when the key rate began."""
    ruonia = carry_rate("rub", days, notes)
    try:
        s = sources.load("cbr:KEYRATE")
        k = ffill_on(s.dates, s.values, days)
    except Exception as e:  # noqa: BLE001 - the Bank of Russia did not answer: RUONIA stands in
        notes.append(f"ключевая ставка не загрузилась ({e}): вместо неё RUONIA")
        return ruonia
    return np.where(np.isfinite(k), k, ruonia)


def kind_rows(kind: str, m: bm.Market, d: Rows, groups: np.ndarray, base: np.ndarray, quality: np.ndarray,
              life_min: float) -> np.ndarray:
    """The rows of week t that `kind` may hold (life at least `life_min`)."""
    g = groups[m.sid[base]]
    dur = m.duration[base]
    life = d.life[base] >= life_min
    if kind == "ofz_short":
        sel = (g == "ofz_fixed") & (dur >= 0.5) & (dur <= 3) & life
    elif kind == "ofz_long":
        sel = (g == "ofz_fixed") & (dur >= 5) & life
    elif kind == "ofz_ladder":
        sel = (g == "ofz_fixed") & (dur >= 0.5) & (dur <= 12) & life
    elif kind in ("ofz_float", "ofz_linker"):
        sel = (g == kind) & life
    else:
        ok = np.isin(base, quality)
        sel = ok & (g == kind) & life & ((dur <= 3) | (kind == "corp_float") | ~np.isfinite(dur))
    return base[sel]


def pick(kind: str, m: bm.Market, d: Rows, cand: np.ndarray, held: list[int], keep: np.ndarray, t: int,
         margin: np.ndarray) -> list[int]:
    """Bond indices for `kind` at week t: the held ones still allowed (`keep`: rows with the sell-side life), then new
    ones - OFZ the most liquid, fixed-coupon corporates the widest spread of the safe set, floaters the widest margin;
    one issue an issuer."""
    corp = kind.startswith("corp")
    most = MAX_CORP if corp else MAX_OFZ
    keep_s = {int(m.sid[r]) for r in keep}
    out = [s for s in held if s in keep_s][:most]
    issuers = {int(d.issuer[m.at(s, t)]) for s in out} if corp else set()
    score = d.value4[cand] if not corp else d.spread[cand] if kind == "corp_fixed" else margin[cand]
    order = cand[np.argsort(-np.nan_to_num(score), kind="stable")]
    for r in order:
        if len(out) >= most:
            break
        s = int(m.sid[r])
        if s in out:
            continue
        if corp:
            i = int(d.issuer[r])
            if i in issuers:
                continue
            issuers.add(i)
        out.append(s)
    return out


def _payments(sched: dict | None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if not sched:
        return (np.zeros(0, np.int64),) * 2 + (np.zeros(0),) * 2  # type: ignore[return-value]
    c = [(bm._ordinal(x[0]), x[1]) for x in sched.get("coupons", []) if x[1] is not None]
    a = [(bm._ordinal(x[0]), x[1]) for x in sched.get("amort", []) if x[1] is not None]
    return (np.array([x[0] for x in c], np.int64), np.array([x[0] for x in a], np.int64),
            np.array([x[1] for x in c], float), np.array([x[1] for x in a], float))


def simulate(m: bm.Market, picks: dict[int, list[int]], sched: dict[str, dict], cash_w: np.ndarray, tax: float,
             cost: float) -> np.ndarray:
    """Weekly return of holding `picks` (rebuilt in equal shares at their weeks), from the first non-empty one."""
    T = len(m.dates)
    ords = np.array([date.fromisoformat(x).toordinal() for x in m.dates])
    r = np.full(T, np.nan)
    weeks = sorted(t for t, p in picks.items() if p)
    if not weeks:
        return r
    pay: dict[int, tuple] = {}
    units: dict[int, float] = {}
    last_v: dict[int, float] = {}
    last_ai: dict[int, float] = {}
    last_mat: dict[int, int] = {}
    cash, nav_prev = 1.0, 1.0
    rebal = set(picks)
    for t in range(weeks[0], T):
        if t > weeks[0]:
            cash *= 1 + (cash_w[t] if math.isfinite(cash_w[t]) else 0.0)  # the week's interest on last week's money
            lo, hi = ords[t - 1], ords[t]
            for s, u in list(units.items()):
                if s not in pay:
                    pay[s] = _payments(sched.get(m.secids[s]))
                cd, ad, cv, av = pay[s]
                coupon = float(cv[(cd > lo) & (cd <= hi)].sum())
                amort = float(av[(ad > lo) & (ad <= hi)].sum())
                k = m.at(s, t)
                if k >= 0:
                    v, ai = m.price[k] / 100 * m.face[k] + m.accint[k], m.accint[k]
                    income = coupon + ai - last_ai[s]
                    last_mat[s] = int(m.mat[k])
                else:  # off the market this week: redeemed (the schedule's last payment or the maturity has passed) or
                    # not traded - then the last value stands
                    redeemed = bool(len(ad) and ad.max() <= hi) or 0 < last_mat.get(s, 0) <= hi
                    v = 0.0 if redeemed else last_v[s]
                    ai = 0.0 if redeemed else last_ai[s]
                    income = coupon
                cash += u * (coupon + amort) - tax * u * max(0.0, income)
                last_v[s], last_ai[s] = v, ai
                if v <= 0:
                    del units[s]
        nav = cash + sum(u * last_v[s] for s, u in units.items())
        if t in rebal:
            nav = _rebalance(m, t, picks[t], units, last_v, last_ai, nav, cost)
            cash = nav - sum(u * last_v[s] for s, u in units.items())
        if t > weeks[0]:
            r[t] = nav / nav_prev - 1
        nav_prev = nav
    return r


def _rebalance(m: bm.Market, t: int, want: list[int], units: dict[int, float], last_v: dict[int, float],
               last_ai: dict[int, float], nav: float, cost: float) -> float:
    """Equal shares of `want` (those with a price at t; a held bond without one stays as it is), the trades' cost out
    of the book; `units` changed in place, the book's value after the cost returned."""
    vals: dict[int, float] = {}
    for s in set(units) | set(want):
        k = m.at(s, t)
        if k >= 0:
            vals[s] = m.price[k] / 100 * m.face[k] + m.accint[k]
            last_v[s], last_ai[s] = vals[s], m.accint[k]
    stuck = {s: u for s, u in units.items() if s not in vals}
    tradable = [s for s in want if s in vals]
    free = nav - sum(u * last_v[s] for s, u in stuck.items())
    paid = 0.0
    for _ in range(3):  # the cost depends on the trades and the trades on what is left after the cost
        each = (free - paid) / len(tradable) if tradable else 0.0
        target = {**stuck, **{s: each / vals[s] for s in tradable}}
        traded = sum(abs(target.get(s, 0.0) - units.get(s, 0.0)) * v for s, v in vals.items())
        paid = cost * traded
    units.clear()
    units.update({s: u for s, u in target.items() if u > 0})
    return nav - paid


@dataclass
class Sleeve:
    dates: list[str]
    returns: dict[str, np.ndarray]  # kinds, mixes, benchmarks; ":tax" - after the coupon tax
    held: dict[str, dict[int, list[int]]]
    notes: list[str]
    today: dict[str, list[dict]]
    policy: dict


def raw_key_rate(days: list[str]) -> np.ndarray:
    """The key rate on `days`, NaN before 2013-09-13 (the regimes need its moves, not RUONIA's noise)."""
    s = sources.load("cbr:KEYRATE")
    return ffill_on(s.dates, s.values, days)


def build(tax: float = TAX, progress=None) -> Sleeve:
    t0 = time.time()
    m = bm.market(progress=progress)
    meta = bm.securities()
    notes: list[str] = []
    d = derive(m, meta)
    T = len(m.dates)
    ends = [t for t in month_ends(m.dates) if m.dates[t] >= START[:7] and t < T - 1] + [T - 1]
    rub = m.units.index("RUB")
    corp_ix = np.array([(meta.get(s) or {}).get("type") in CORP_TYPES for s in m.secids])
    # schedules: every OFZ and every ruble corporate liquid enough at some month-end
    want: set[int] = {j for j, s in enumerate(m.secids) if ofz_kind(s)}
    for t in ends:
        base = _eligible_base(m, d, bm.cross_section(m, t), t)
        want |= {int(s) for s in m.sid[base] if corp_ix[s]}
    sched = bm.schedules([m.secids[j] for j in sorted(want)], progress)
    apply_offers(m, d, sched)
    groups = np.array(classify(m, meta, sched), dtype=object)
    margin = coupon_margin(m, sched, groups, key_rate(m.dates, notes))
    risk = risk_one()
    if risk is None:
        notes.append("нет списка T-Invest из server-analytic-system: корпоративные сегодня — без проверки риска брокера")
    rate = carry_rate("rub", m.dates, notes)
    ords = np.array([date.fromisoformat(x).toordinal() for x in m.dates])
    cash_w = np.r_[np.nan, rate[:-1] * np.diff(ords) / 365]
    picks: dict[str, dict[int, list[int]]] = {k: {} for k, _ in KINDS}
    for t in ends:
        rows = bm.cross_section(m, t)
        base = _eligible_base(m, d, rows, t)
        quality = corp_quality(m, d, base, t, risk if t == T - 1 else None, groups, margin)
        sell_base = rows[(m.unit[rows] == rub) & d.order_ok[rows]]
        sell_quality = corp_quality(m, d, sell_base, t, None, groups, margin, loose=True)
        for kind, _ in KINDS:
            cand = kind_rows(kind, m, d, groups, base, quality, BUY_LIFE)
            keep = kind_rows(kind, m, d, groups, sell_base, sell_quality, SELL_LIFE)
            prev = [p for tt, p in picks[kind].items() if tt < t]
            picks[kind][t] = pick(kind, m, d, cand, prev[-1] if prev else [], keep, t, margin)
    returns: dict[str, np.ndarray] = {}
    for kind, _ in KINDS:
        c = COST["corp" if kind.startswith("corp") else "ofz"]
        returns[kind] = simulate(m, picks[kind], sched, cash_w, 0.0, c)
        returns[f"{kind}:tax"] = simulate(m, picks[kind], sched, cash_w, tax, c)
    for key, _, mix in MIXES:
        for suffix in ("", ":tax"):
            returns[key + suffix] = blend({k: returns[k + suffix] for k in mix}, mix)
    returns["cash"] = cash_w
    for key, sid in (("RGBITR", "moex:index:RGBITR"), ("SBGB", "moex:shares:SBGB")):
        try:
            returns[key] = benchmark(sid, m.dates)
        except Exception as e:  # noqa: BLE001 - a benchmark did not load: the rest stands
            notes.append(f"{key} не загрузился: {e}")
    try:  # RUCBITR (after the coupon tax) ends in May 2023: to 2018 it, then RUCBTRNS (gross), as the book of sleeves
        a, b = benchmark("moex:index:RUCBITR", m.dates), benchmark("moex:index:RUCBTRNS", m.dates)
        switch = np.array([x > CORP_SWITCH for x in m.dates])
        switch[1:] &= switch[:-1]
        returns["RUCB"] = np.where(switch, b, a)
    except Exception as e:  # noqa: BLE001
        notes.append(f"индексы корпоративных облигаций не загрузились: {e}")
    today = {kind: describe(m, d, picks[kind].get(T - 1, []), T - 1, groups, margin) for kind, _ in KINDS}
    policy = policy_mixes(m.dates, ends, returns, notes)
    policy["issues"] = issues(policy["mix"], today)
    policy["plan"] = plan_issues(policy["mix"], today)
    notes.append(f"рынок облигаций: {len(m.dates)} недель с {m.dates[0]}, {len(m.secids)} выпусков; "
                 f"графики выплат — {len(sched)}; {time.time() - t0:.0f} с")
    return Sleeve(dates=m.dates, returns=returns, held=picks, notes=notes, today=today, policy=policy)


POLICY_ROWS = [("base", "База: корпоративные флоатеры 50%, короткие ОФЗ и корпоративные по 25%"),
               ("policy_rule", "По режиму ЦБ: доли, заданные заранее"),
               ("policy", "По режиму ЦБ: оптимум на прошлых месяцах режима")]


def policy_mixes(days: list[str], ends: list[int], returns: dict[str, np.ndarray], notes: list[str]) -> dict:
    """The base mix, the regime's prior and its walk-forward optimum (chosen on the after-tax returns) into `returns`;
    today's regime and mixes."""
    try:
        key = raw_key_rate(days)
    except Exception as e:  # noqa: BLE001 - no key rate: every month is a pause
        notes.append(f"ключевая ставка не загрузилась ({e}): режим ЦБ везде «пауза»")
        key = np.full(len(days), np.nan)
    regime = bp.regimes(days, key)
    rules, opts = bp.walk_forward({k: returns[f"{k}:tax"] for k in bp.CANDIDATES}, ends, regime)
    for suffix in ("", ":tax"):
        S = {k: returns[k + suffix] for k in bp.CANDIDATES}
        returns["base" + suffix] = blend({k: returns[k + suffix] for k in bp.BASE}, bp.BASE)
        returns["policy_rule" + suffix] = bp.dynamic_blend(S, rules, len(days))
        returns["policy" + suffix] = bp.dynamic_blend(S, opts, len(days))
    return bp.describe(regime, days, key, rules, opts)


PLAN_ISSUES = 15  # issues in the account's plan: every one is an order placed by hand


def plan_issues(mix: dict[str, float], today: dict[str, list[dict]], most: int = PLAN_ISSUES) -> list[dict]:
    """The issues for the account: each kind's share of `mix` among round(share x `most`) of its issues (at least one;
    the ladder's spread evenly over its durations, the others in the kind's own order - OFZ the most liquid,
    corporates the widest spread or margin of the safe set). An issue two kinds hold is one row with both shares."""
    held = {k: w for k, w in mix.items() if today.get(k)}
    total = sum(held.values())
    by: dict[str, dict] = {}
    for k, w in held.items():
        items = today[k]
        n = min(len(items), max(1, round(w / total * most)))
        if k == "ofz_ladder":
            items = sorted(items, key=lambda b: b["duration"] or 0.0)
            chosen = [items[round(i * (len(items) - 1) / max(n - 1, 1))] for i in range(n)] if n > 1 else [items[len(items) // 2]]
        else:
            chosen = items[:n]
        for b in chosen:
            if b["secid"] in by:
                by[b["secid"]]["weight"] += w / total / n
            else:
                by[b["secid"]] = {**b, "kind": k, "weight": w / total / n}
    return sorted(by.values(), key=lambda x: (-x["weight"], x["secid"]))


def issues(mix: dict[str, float], today: dict[str, list[dict]]) -> list[dict]:
    """The sleeve's issues today: each kind's share of `mix` split equally among its issues (a kind with none today
    gives its share to the others)."""
    held = {k: w for k, w in mix.items() if today.get(k)}
    total = sum(held.values())
    out = []
    for k, w in held.items():
        for b in today[k]:
            out.append({**b, "kind": k, "weight": w / total / len(today[k])})
    return sorted(out, key=lambda x: -x["weight"])


CORP_SWITCH = "2018-12-29"  # RUCBTRNS starts


def benchmark(sid: str, days: list[str]) -> np.ndarray:
    """Weekly return of a series on `days`; NaN once it has ended (a week after its last day): no zero returns made up
    by carrying the last value forward."""
    s = sources.load(sid)
    v = ffill_on(s.dates, s.values, days)
    end = (date.fromisoformat(s.dates[-1]).toordinal() + 7)
    v[np.array([date.fromisoformat(x).toordinal() > end for x in days])] = np.nan
    return np.r_[np.nan, v[1:] / v[:-1] - 1]


def blend(series: dict[str, np.ndarray], mix: dict[str, float]) -> np.ndarray:
    """Weekly return of the kinds in fixed shares (rebalanced weekly); a kind not started yet gives its share to the
    others."""
    keys = list(mix)
    R = np.column_stack([series[k] for k in keys])
    w = np.array([mix[k] for k in keys])
    ok = np.isfinite(R)
    ww = np.where(ok, w, 0.0)
    tot = ww.sum(axis=1)
    out = np.where(tot > 0, (np.nan_to_num(R) * ww).sum(axis=1) / np.where(tot > 0, tot, 1), np.nan)
    return out


def describe(m: bm.Market, d: Rows, sids: list[int], t: int, groups: np.ndarray, margin: np.ndarray) -> list[dict]:
    out = []
    for s in sids:
        k = m.at(s, t)
        if k < 0:
            continue
        out.append({"secid": m.secids[s], "name": m.names.get(m.secids[s], m.secids[s]), "price": float(m.price[k]),
                    "accint": float(m.accint[k]), "face": float(m.face[k]),
                    "ytm": None if not math.isfinite(m.ytm[k]) else float(m.ytm[k]),
                    "duration": None if not math.isfinite(m.duration[k]) else float(m.duration[k]),
                    "spread": None if groups[s] == "ofz_linker" or not math.isfinite(d.spread[k]) else float(d.spread[k]),
                    "life": float(d.life[k]) if math.isfinite(d.life[k]) else None,
                    "margin": None if not math.isfinite(margin[k]) else float(margin[k]),
                    "value4": float(d.value4[k]), "group": groups[s]})
    return out


BENCHMARKS = [("RGBITR", "индекс ОФЗ RGBITR"), ("RUCB", "индекс корпоративных (RUCBITR, с 2019 — RUCBTRNS)"),
              ("SBGB", "фонд ОФЗ SBGB"), ("cash", "деньги, RUONIA")]
RECENT = 5  # years: the window every kind but the youngest has


def report(tax: float = TAX, start: str = START, progress=None) -> dict:
    """Every kind, mix and benchmark: since its start (not before `start`) and over the last RECENT years; the yearly
    returns; today's issues of every kind."""
    from .book import stats, thin_idx, years_table
    sl = build(tax, progress)
    days, cash = sl.dates, sl.returns["cash"]
    i0 = next(i for i, d in enumerate(days) if d >= start)
    recent = date.fromisoformat(days[-1]).replace(year=date.fromisoformat(days[-1]).year - RECENT).isoformat()
    j0 = next(i for i, d in enumerate(days) if d >= recent)
    titles = {**KIND_TITLES, **{k: t for k, t, _ in MIXES}, **dict(POLICY_ROWS), **dict(BENCHMARKS)}
    rows = []
    for key in [k for k, _ in KINDS] + [k for k, _, _ in MIXES] + [k for k, _ in POLICY_ROWS] + [k for k, _ in BENCHMARKS]:
        x = sl.returns.get(key)
        if x is None:
            continue
        ok = np.flatnonzero(np.isfinite(x[i0:]))
        if not len(ok):
            continue
        whole = stats(x[i0:], cash[i0:], days[i0:])
        last = stats(x[j0:], cash[j0:], days[j0:])
        taxed = sl.returns.get(f"{key}:tax")
        held = [len(p) for t, p in sl.held.get(key, {}).items() if t >= i0]
        rows.append({"key": key, "title": titles[key], "from": days[i0 + int(ok[0])], "whole": whole, "recent": last,
                     "whole_tax": stats(taxed[i0:], cash[i0:], days[i0:]) if taxed is not None else None,
                     "recent_tax": stats(taxed[j0:], cash[j0:], days[j0:]) if taxed is not None else None,
                     "issues": float(np.mean(held)) if held else None})
    years = years_table(days[i0:], {r["key"]: sl.returns[r["key"]][i0:] for r in rows})
    idx = thin_idx(len(days) - i0)
    curves: dict[str, list] = {}
    for r in rows:
        for key in (r["key"], f"{r['key']}:tax"):
            x = sl.returns.get(key)
            if x is None:
                continue
            x = x[i0:]
            grow = np.cumprod(1 + np.nan_to_num(x))
            first = int(np.flatnonzero(np.isfinite(x))[0]) if np.isfinite(x).any() else len(x)
            curves[key] = [None if i < first else float(grow[i] / grow[first]) for i in idx]
    return {"date": days[-1], "start": days[i0], "recent_from": days[j0], "tax": tax, "rows": rows, "years": years,
            "curves": {"dates": [days[i0 + i] for i in idx], "series": curves},
            "today": sl.today, "notes": sl.notes, "titles": titles, "policy": sl.policy,
            "params": {"buy_life": BUY_LIFE, "sell_life": SELL_LIFE, "min_value": MIN_VALUE, "spread_cap": SPREAD_CAP,
                       "float_margin": FLOAT_MARGIN, "max_corp": MAX_CORP, "max_ofz": MAX_OFZ, "cost": COST}}
