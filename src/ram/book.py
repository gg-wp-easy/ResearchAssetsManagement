"""The book of sleeves: MOEX shares picked by the factor lab, bonds, the trade bot's trend book and the money market,
combined by a risk budget and capped so that no scenario on the list takes more than a set share of the capital; every
decision is logged with its reasons.

Weekly, on the TQBR panel's weeks (universe.py), rebalanced at each month-end - the day the equity sleeve picks its
shares. Every weight uses only what was known on its date:

- equity: the top fifth of the 100 most traded shares by a score known at the month-end (factors.build_months), equal
  weights drifting within the month, the turnover paid at `cost` per side; or all 100 equally; or the MCFTR index;
- bonds: MOEX's total-return index of OFZ (RGBITR) or of corporate bonds (RUCBITR - after the coupon tax - to 2018,
  RUCBTRNS - gross - from 2019);
- trend: the bot's main book (rule.py on the preset `main` or `main_guard`, its own drawdown control) on capital held in
  the money market: RUONIA plus the rule's excess return; its positions are known every day;
- cash: RUONIA.

Risk budget: on the last 156 weeks (at least 52) of the sleeves' weekly returns over cash, the Ledoit-Wolf covariance
Sigma; the weights w >= 0 whose risk contributions w_i (Sigma w)_i / (w' Sigma w) equal the budget b_i, scaled to the
target volatility, sum w <= 1 (no borrowing), the rest in cash. Or given shares of the capital.

Scenario cap: a scenario is a joint move v of the four markets the trend book trades (yuan, gold in rubles, MCFTR,
RGBITR) - the bot's hypothetical ones and the windows of scenarios.WINDOWS that ended before the date (short ones whole,
longer ones each 5-day move). The sleeves move by beta_e v_MCFTR (the equity sleeve's beta to MCFTR on the window, not
below 1: in a crash the correlations go up), beta_b v_RGBITR (OFZ: 1; corporates: their beta, not below 1) and pos . v
(the trend book's positions of the date: a gap leaves no time to turn them); cash does not move. If the worst loss
-w . m(v) exceeds the limit L, the sleeves are cut by the least squared loss of risk budget that meets it (cap): the
sleeve that loses most per unit of its budget is cut most, a hedge is kept.

Every week the month's target (times the drawdown control's multiplier) is capped again on that week's trend positions;
the book trades to it when its drifted weights break the limit or a sleeve is more than BAND away from it.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, replace
from datetime import date

import numpy as np
from scipy.optimize import minimize
from scipy.stats import rankdata

from . import events, factors, ml, sizing, sources, universe
from .allocation import shrunk_cov
from .assets import AssetSpec, build, carry_rate, ffill_on
from .factors import rank_z
from .presets import PRESETS
from .rule import CONTROLS, Params, multiplier, simulate
from .scenarios import BOT_HYPOTHETICAL, NO_EXIT, WINDOWS, window_moves

EQUITY = [("composite", "отбор: моментум, низкая волатильность, E/P, FCF/P"),
          ("gbm", "отбор: ML-бустинг ценовых факторов"),
          ("ew", "все 100 бумаг поровну"),
          ("mcftr", "индекс MCFTR")]
BONDS = [("ofz", "ОФЗ (RGBITR)"), ("corp", "корпоративные (RUCBITR → RUCBTRNS)")]
TRENDS = [("main", "основной счёт бота"), ("main_guard", "основной с защитой")]
SLEEVES = ["equity", "bonds", "trend", "cash"]
SLEEVE_TITLES = {"equity": "акции", "bonds": "облигации", "trend": "тренд бота", "cash": "деньги"}
MARKETS = ["юань", "золото в рублях", "MCFTR", "ОФЗ"]  # the trend book's assets: the scenarios' coordinates
COMPOSITE = ["mom", "lowvol", "ep", "fcfp"]
UNIVERSE_START, TOP = "2015-01-01", 100  # the factor lab's and ML page's defaults: their caches are shared
WINDOW, MIN_WEEKS, WEEKS = 156, 52, 52
REBALANCE_COST = 0.001  # per side, moving capital between sleeves
CAP_BUFFER = 0.95  # a cut brings the worst loss to 95% of the limit: the weights' drift does not trip it next week
LIMITS = (0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.0)  # the price of the cap: the book at each limit (0: none)
BAND = 0.05  # between month-ends the book trades only when a sleeve is this far (share of the capital) from its target
CORP_SWITCH = "2018-12-29"  # RUCBTRNS starts


@dataclass(frozen=True)
class Opts:
    equity: str = "composite"
    bonds: str = "ofz"
    trend: str = "main"
    method: str = "risk"  # risk: risk budget and target volatility | weights: given shares of the capital
    budget: tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3)  # equity, bonds, trend
    target_vol: float = 0.10
    limit: float = 0.25  # the largest loss in any scenario, share of the capital (0: no cap)
    control: int = 0  # rule.CONTROLS, on the book's own drawdown
    cost: float = 0.002  # per side, the equity sleeve's share trades
    start: str = "2016-01-01"
    events: bool = True  # the equity sleeve sells a share on an exchange event (events.py)

    @staticmethod
    def from_dict(d: dict) -> "Opts":
        known = {k: v for k, v in d.items() if k in Opts.__dataclass_fields__}
        if "budget" in known:
            b = known["budget"]
            if isinstance(b, dict):
                b = [b.get(k, 0.0) for k in SLEEVES[:3]]
            known["budget"] = tuple(max(0.0, float(x)) for x in b)
        for k in ("target_vol", "limit", "cost"):
            if k in known:
                known[k] = float(known[k])
        if "control" in known:
            known["control"] = int(known["control"])
        if "events" in known:
            known["events"] = bool(known["events"])
        if "start" in known:
            known["start"] = date.fromisoformat(str(known["start"])[:10]).isoformat()
        o = Opts(**known)
        if o.equity not in dict(EQUITY) or o.bonds not in dict(BONDS) or o.trend not in dict(TRENDS):
            raise ValueError("блок: акции — " + ", ".join(dict(EQUITY)) + "; облигации — " + ", ".join(dict(BONDS))
                             + "; тренд — " + ", ".join(dict(TRENDS)))
        if o.method not in ("risk", "weights"):
            raise ValueError("распределение: risk (бюджет риска) или weights (доли капитала)")
        if len(o.budget) != 3 or not sum(o.budget) > 0:
            raise ValueError("бюджет: три неотрицательных числа (акции, облигации, тренд), хотя бы одно больше нуля")
        if o.method == "weights" and sum(o.budget) > 1 + 1e-9:
            raise ValueError("доли капитала в сумме не больше 100% (остальное — деньги)")
        if not 0.01 <= o.target_vol <= 0.5:
            raise ValueError("целевая волатильность — от 1% до 50% в год")
        if not 0 <= o.limit < 1:
            raise ValueError("предел потерь в сценарии — от 0 (без предела) до 100%")
        if not 0 <= o.control < len(CONTROLS):
            raise ValueError("контроль просадки: номер из списка")
        if not 0 <= o.cost <= 0.05:
            raise ValueError("издержки — от 0 до 5% за сторону")
        return o

    def as_dict(self) -> dict:
        d = asdict(self)
        d["budget"] = dict(zip(SLEEVES[:3], self.budget))
        return d


# ---------------------------------------------------------------------------- the sleeves


@dataclass
class Data:
    """Every sleeve on the panel's weeks, built once per panel."""
    dates: list[str]
    ends: list[int]  # month-end weeks
    returns: dict[str, np.ndarray]  # "equity:composite", "bonds:ofz", "trend:main", "cash", ...: W weekly returns
    picks: dict[str, dict[int, list[str]]]  # equity sleeve -> formation week -> tickers
    pos: dict[str, np.ndarray]  # trend sleeve -> W x 4 positions held after the week's end, share of the sleeve
    mkt: np.ndarray  # W x 2 weekly total returns of MCFTR and RGBITR
    scenarios: list[dict]  # label, kind (hyp | hist), to (the window's last day), moves (S x 4)
    names: dict[str, str]
    notes: list[str]
    panel_to: str
    sales: dict[str, list[dict]] = None  # equity sleeve -> shares sold on exchange events
    exits: dict = None  # ticker -> event spans (events.exits)
    events_from: str | None = None  # the news the filter has seen start here
    fut_xr: np.ndarray = None  # W x 4 weekly excess returns of the trend book's markets (a futures contract's return)
    fut_px: np.ndarray = None  # W x 4 their price levels (to scale today's contract value back in time)


_cache: dict[tuple, Data] = {}


def data(cost: float) -> Data:
    p = universe.panel()
    key = (p.dates[-1], len(p.tickers), round(cost, 6))
    if key not in _cache:
        _cache.clear()
        _cache[key] = _build(p, cost)
    return _cache[key]


def _build(p: universe.Panel, cost: float) -> Data:
    notes = list(p.notes)
    months, warns = factors.build_months(p, UNIVERSE_START, TOP)
    notes += warns
    W = len(p.dates)
    returns: dict[str, np.ndarray] = {}
    picks: dict[str, dict[int, list[str]]] = {}
    preds = ml.forecasts(p, months, UNIVERSE_START, TOP).get("price", {}).get("gbm", {}).get("preds", {})
    try:
        evs, cov = events.all_events()
        exits = events.exits(evs)
    except Exception as e:  # noqa: BLE001 - the exchange's news did not load: the sleeves without the filter
        evs, cov, exits = [], {"from": None}, {}
        notes.append(f"новости Мосбиржи не загрузились ({e}): отбор без фильтра событий")
    sales: dict[str, list[dict]] = {}
    for key, _ in EQUITY:
        if key == "mcftr":
            returns["equity:mcftr"] = index_weekly(p.dates, "moex:index:MCFTR")
            continue
        r, pk, sold = equity_sleeve(p, months, key, cost, preds, exits)
        returns[f"equity:{key}"], picks[key], sales[key] = r, pk, sold
        r, pk, _ = equity_sleeve(p, months, key, cost, preds, None)
        returns[f"equity:{key}:raw"], picks[f"{key}:raw"] = r, pk
    returns["bonds:ofz"] = index_weekly(p.dates, "moex:index:RGBITR")
    returns["bonds:corp"] = corporate_weekly(p.dates)
    rate = carry_rate("rub", p.dates, notes)
    ords = np.array([date.fromisoformat(d).toordinal() for d in p.dates])
    returns["cash"] = np.r_[np.nan, rate[:-1] * np.diff(ords) / 365]
    pos: dict[str, np.ndarray] = {}
    scen: list[dict] = []
    fut_xr = fut_px = None
    for key, _ in TRENDS:
        r, ps, b = trend_sleeve(key, p.dates, notes)
        returns[f"trend:{key}"], pos[key] = r, ps
        if not scen:
            scen = scenario_set(b)
            fut_xr, fut_px = market_weekly(b, p.dates)
    mkt = np.column_stack([returns["equity:mcftr"], returns["bonds:ofz"]])
    ends = [t for t in factors.month_ends(p.dates) if t < W - 1]  # the panel's last week is a month-end only by chance
    return Data(dates=p.dates, ends=ends, returns=returns, picks=picks, pos=pos, mkt=mkt,
                scenarios=scen, names=dict(p.names), notes=notes, panel_to=p.dates[-1],
                sales=sales, exits=exits, events_from=cov.get("from"), fut_xr=fut_xr, fut_px=fut_px)


def market_weekly(b, dates: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """(W x 4 weekly excess returns, W x 4 price levels) of the trend book's markets on the panel's weeks."""
    idx = np.searchsorted(np.array(b.dates), np.array(dates), side="right") - 1
    E = np.where((idx >= 0)[:, None], b.E[np.clip(idx, 0, None)], np.nan)
    P = np.where((idx >= 0)[:, None], b.P[np.clip(idx, 0, None)], np.nan)
    xr = np.vstack([np.full(b.n, np.nan), E[1:] / E[:-1] - 1])
    return xr, P


def composite(m: factors.Month) -> np.ndarray | None:
    """The mean rank (unit variance) of the factors known for at least a third of the universe; a missing value: 0."""
    zs = []
    for k in COMPOSITE:
        v = m.f.get(k)
        if v is None or np.isfinite(v).mean() < 1 / 3:
            continue
        z, ok = np.zeros(len(v)), np.isfinite(v)
        z[ok] = rank_z(v[ok])
        zs.append(z)
    return np.mean(zs, axis=0) if zs else None


def top_fifth(score: np.ndarray) -> np.ndarray:
    """Positions of the highest fifth by score (the factor lab's quintile Q5)."""
    ok = np.flatnonzero(np.isfinite(score))
    rank = rankdata(score[ok])
    q = np.minimum(((rank - 1) * 5 / len(ok)).astype(int), 4)
    return ok[q == 4]


def equity_sleeve(p: universe.Panel, months: list[factors.Month], key: str, cost: float,
                  preds: dict[int, list[float]], exits: dict | None = None):
    """Weekly return of the equal-weight basket picked at each month-end, drifting until the next one; the first week
    pays 2 x cost x the share of names replaced. With `exits` (events.exits): a share with an exchange event in force
    is not picked, and one whose news comes within the month is sold at the end of that week - its money spread over
    the rest at 2 x cost. Returns (returns, picks, sales)."""
    r = np.full(len(p.dates), np.nan)
    picks: dict[int, list[str]] = {}
    sales: list[dict] = []
    prev: set[str] | None = None
    for k, m in enumerate(months):
        day = p.dates[m.t]
        out = np.array([bool(exits) and events.excluded(exits.get(p.tickers[j]), day) is not None for j in m.cols])
        if key == "ew":
            sel = np.flatnonzero(~out)
        else:
            score = composite(m) if key == "composite" else (np.array(preds[k]) if k in preds else None)
            if score is None:
                prev = None
                continue
            sel = top_fifth(np.where(out, np.nan, score))
        cols = m.cols[sel]
        names = {p.tickers[j] for j in cols}
        turn = 1 - len(names & prev) / len(names) if prev else 1.0
        prev = names
        v = np.full(len(cols), 1 / len(cols))
        for w in range(m.t + 1, m.u + 1):
            rw = np.nan_to_num(p.R[w, cols])  # a share off the board: held at its last price, as the lab does
            r[w] = float(v @ (1 + rw) / v.sum() - 1)
            v = v * (1 + rw)
            if exits:  # news during the week: sold at its end
                for q, j in enumerate(cols):
                    if v[q] <= 0:
                        continue
                    hit = next((e for a, _, e in exits.get(p.tickers[j], []) if p.dates[w - 1] <= a < p.dates[w]), None)
                    if hit is None:
                        continue
                    total, freed = v.sum(), v[q]
                    v[q] = 0.0
                    if v.sum() > 0:
                        v = v * total / v.sum()
                    r[w] -= 2 * cost * freed / total
                    prev.discard(p.tickers[j])
                    sales.append({"week": w, "ticker": p.tickers[j], "share": float(freed / total), "kind": hit.kind,
                                  "news": hit.date, "url": hit.url, "issuer": hit.issuer})
        r[m.t + 1] -= 2 * cost * turn
        picks[m.t] = sorted(names)
    return r, picks, sales


def index_weekly(dates: list[str], sid: str) -> np.ndarray:
    s = sources.load(sid)
    v = ffill_on(s.dates, s.values, dates)
    return np.r_[np.nan, v[1:] / v[:-1] - 1]


def corporate_weekly(dates: list[str]) -> np.ndarray:
    a, b = sources.load("moex:index:RUCBITR"), sources.load("moex:index:RUCBTRNS")
    va, vb = ffill_on(a.dates, a.values, dates), ffill_on(b.dates, b.values, dates)
    r_a, r_b = np.r_[np.nan, va[1:] / va[:-1] - 1], np.r_[np.nan, vb[1:] / vb[:-1] - 1]
    switch = np.array([d > CORP_SWITCH for d in dates])
    switch[1:] &= np.array([d > CORP_SWITCH for d in dates[:-1]])
    return np.where(switch, r_b, r_a)


def trend_sleeve(key: str, dates: list[str], notes: list[str]):
    """(weekly return, W x 4 positions after each week's end, the basket) of the bot's preset on money-market capital."""
    pr = next(x for x in PRESETS if x["key"] == key)
    b = build([AssetSpec.from_dict(a) for a in pr["assets"]], pr.get("history_from"))
    run = simulate(b, Params.from_dict(pr["params"]), CONTROLS[pr.get("control", 0)])
    rate = carry_rate("rub", b.dates, notes)
    ords = np.array([date.fromisoformat(d).toordinal() for d in b.dates])
    daily = run.x + np.r_[0.0, rate[:-1] * np.diff(ords) / 365]
    cum = np.r_[0.0, np.cumsum(np.log1p(daily))]  # cum[i + 1]: log value after day i
    idx = np.searchsorted(np.array(b.dates), np.array(dates), side="right") - 1
    r = np.full(len(dates), np.nan)
    ok = (idx[1:] >= 0) & (idx[:-1] >= 0)
    r[1:][ok] = np.expm1(cum[idx[1:][ok] + 1] - cum[idx[:-1][ok] + 1])
    T = len(b.dates)
    pos = np.array([run.pos[min(i + 1, T - 1)] if i >= 0 else np.zeros(b.n) for i in idx])
    return r, pos, b


def scenario_set(b) -> list[dict]:
    """The bot's hypothetical moves of its four markets and the crisis windows' moves (point in time by `to`)."""
    out = [{"label": label, "kind": "hyp", "to": "", "moves": np.array([moves], float)} for label, moves in BOT_HYPOTHETICAL]
    for label, a, z, _region in WINDOWS:
        if z < b.dates[0] or a > b.dates[-1]:
            continue
        i, k = b.index_of(a), b.index_of(z)
        if k <= i:
            continue
        if any(t in label for t in NO_EXIT) or k - i <= 5:
            vecs, name = [window_moves(b, a, z)], label
        else:
            with np.errstate(invalid="ignore", divide="ignore"):
                vecs, name = [b.E[t + 5] / b.E[t] - 1 for t in range(i, k - 4)], label + " (каждые 5 дн.)"
        out.append({"label": name, "kind": "hist", "to": b.dates[k], "moves": np.nan_to_num(np.array(vecs, float))})
    return out


# ---------------------------------------------------------------------------- the decisions


def budget_weights(cov: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Long weights summing to 1 whose risk contributions are the budget b (> 0): the minimum of
    1/2 y' Sigma y - b' ln y, normalized (Spinu 2013) - convex, one solution for any covariance."""
    b = b / b.sum()
    y0 = b / np.sqrt(np.diag(cov))
    res = minimize(lambda y: 0.5 * y @ cov @ y - b @ np.log(y), y0, jac=lambda y: cov @ y - b / y,
                   bounds=[(1e-12, None)] * len(b), method="L-BFGS-B", options={"ftol": 1e-15, "gtol": 1e-12})
    y = res.x if res.success else y0
    return y / y.sum()


def contributions(cov: np.ndarray, w: np.ndarray) -> np.ndarray:
    total = float(w @ cov @ w)
    return w * (cov @ w) / total if total > 0 else np.zeros(len(w))


def cap(w: np.ndarray, moves: np.ndarray, prio: np.ndarray, limit: float) -> np.ndarray:
    """The share c_k in [0, 1] of each risky sleeve to keep so that no scenario vector loses more than `limit`:
        min  sum_k prio_k (1 - c_k)^2   s.t.  -sum_k c_k w_k m_k(v) <= limit  for every vector v
    (prio - the sleeves' risk contributions). At the optimum 1 - c_k is proportional to the sleeve's share of the binding
    losses per unit of its budget: the sleeve that loses most is cut most, a hedge is kept, and a small change of the
    trend's positions moves the cut a little (a linear program would jump between corners). c = 0 always satisfies it."""
    A = -(moves * w[None, :])
    A = A[np.clip(A, 0, None).sum(axis=1) > limit]  # only a vector that can break the limit inside the box matters
    if not len(A):
        return np.ones(len(w))
    p = np.maximum(prio, 1e-6)
    worst = float(A.sum(axis=1).max())
    c0 = np.full(len(w), min(1.0, limit / worst) if worst > 0 else 1.0)  # the proportional cut: feasible
    res = minimize(lambda c: float(p @ (1 - c) ** 2), c0, jac=lambda c: -2 * p * (1 - c), method="SLSQP",
                   bounds=[(0.0, 1.0)] * len(w),
                   constraints=[{"type": "ineq", "fun": lambda c: limit - A @ c, "jac": lambda c: -A}],
                   options={"ftol": 1e-12, "maxiter": 200})
    c = np.clip(res.x, 0.0, 1.0) if res.success else c0
    return c if float((A @ c).max()) <= limit + 1e-7 else c0


def beta(y: np.ndarray, x: np.ndarray) -> float:
    ok = np.isfinite(y) & np.isfinite(x)
    if ok.sum() < MIN_WEEKS or x[ok].var() == 0:
        return 1.0
    xs, ys = x[ok], y[ok]
    return float(((xs - xs.mean()) * (ys - ys.mean())).mean() / xs.var())


@dataclass
class Book:
    o: Opts
    keys: list[str]  # the four return series: equity, bonds, trend, cash
    R: np.ndarray  # W x 4
    pos: np.ndarray  # W x 4 the trend book's positions
    picks: dict[int, list[str]]


def equity_key(o: Opts) -> str:
    return o.equity if o.events or o.equity == "mcftr" else f"{o.equity}:raw"


def assemble(d: Data, o: Opts) -> Book:
    keys = [f"equity:{equity_key(o)}", f"bonds:{o.bonds}", f"trend:{o.trend}", "cash"]
    return Book(o=o, keys=keys, R=np.column_stack([d.returns[k] for k in keys]), pos=d.pos[o.trend],
                picks=d.picks.get(equity_key(o), {}))


def ready(bk: Book, t: int) -> np.ndarray:
    """Which risky sleeves have at least MIN_WEEKS of the window up to week t."""
    lo = max(1, t - WINDOW + 1)
    return np.isfinite(bk.R[lo:t + 1, :3]).sum(axis=0) >= MIN_WEEKS


def first_week(d: Data, bk: Book) -> int:
    """The first month-end on or after the start at which every sleeve with a budget is ready."""
    need = np.array(bk.o.budget) > 0
    for t in d.ends:
        if d.dates[t] >= bk.o.start and t >= MIN_WEEKS and (ready(bk, t) | ~need).all():
            return t
    raise ValueError("ни на одну дату после начала у блоков с бюджетом не хватает истории (нужен год)")


class Scenarios:
    """The scenario moves known at a date, flattened: one row per move vector, `group` the scenario it belongs to."""

    def __init__(self, d: Data, day: str):
        self.items = [s for s in d.scenarios if s["kind"] == "hyp" or s["to"] < day]
        self.V = np.vstack([s["moves"] for s in self.items])
        self.group = np.concatenate([[g] * len(s["moves"]) for g, s in enumerate(self.items)])

    def sleeve_moves(self, pos: np.ndarray, b_eq: float, b_bd: float) -> np.ndarray:
        """S x 3: the move of each risky sleeve in each vector."""
        return np.column_stack([b_eq * self.V[:, 2], b_bd * self.V[:, 3], self.V @ pos])

    def losses(self, w: np.ndarray, moves: np.ndarray) -> np.ndarray:
        """The loss of each scenario (its worst vector) for risky weights w; a gain is a negative loss."""
        loss = -(moves @ w)
        out = np.full(len(self.items), -np.inf)
        np.maximum.at(out, self.group, loss)
        return out


def run(d: Data, o: Opts, t0: int | None = None, log: bool = False) -> dict:
    """The book week by week from the first ready month-end (or t0): weekly returns, weights, the decision log."""
    bk = assemble(d, o)
    t0 = first_week(d, bk) if t0 is None else t0
    W = len(d.dates)
    ends = set(d.ends)
    control = CONTROLS[o.control]
    budget = np.array(o.budget, float)
    x = np.full(W, np.nan)
    held = np.zeros((W, 4))  # weights after the week's decisions
    h = np.r_[np.zeros(3), 1.0]
    base = h.copy()  # the month's weights before the control
    eq, peak, halt = 1.0, 1.0, 0
    peaks: list[float] = []
    cut_weeks, adjust_weeks, binding, rows = 0, 0, 0, []
    worst_after = np.zeros(W)
    scen: Scenarios | None = None
    betas, prio = (1.0, 1.0), np.ones(3)
    pending = 0.0  # the cost of the last week's trades, paid out of the next week's return
    for t in range(t0, W):
        if t > t0:
            r = np.nan_to_num(bk.R[t])
            x[t] = float(h @ r) - pending
            h = h * (1 + r)
            h = h / h.sum()
            eq *= 1 + x[t]
            if control.rolling:
                peaks.append(eq)
                peaks = peaks[-max(1, control.rolling // 5):]
                peak = max(peaks)
            else:
                peak = max(peak, eq)
        pending = 0.0
        dd = 1 - eq / peak
        if control.kind == "stop":
            if halt == 0 and dd >= control.limit:
                halt = 4  # the bot pauses 21 trading days
            m = 0.0 if halt else 1.0
            if halt:
                halt -= 1
                if halt == 0:
                    peak, peaks = eq, [eq]
        else:
            m = multiplier(control, dd)
        day = d.dates[t]
        decided = None
        if t in ends or t == t0:
            scen = Scenarios(d, day)
            decided = decide(d, bk, t, budget, scen)
            base, betas, prio = decided["w"], decided["betas"], decided["prio"]
        # the month's target after the control, capped on this week's trend positions
        want = np.r_[base[:3] * m, 1 - base[:3].sum() * m]
        moves = scen.sleeve_moves(bk.pos[t], *betas)
        c = np.ones(3)
        if o.limit > 0 and scen.losses(want[:3], moves).max() > o.limit + 1e-9:
            c = cap(want[:3], moves, prio, o.limit * CAP_BUFFER)
            want = np.r_[want[:3] * c, 1 - (want[:3] * c).sum()]
        loss_h = scen.losses(h[:3], moves)
        event = None
        if decided is not None:
            new = want
            binding += int((c < 1 - 1e-6).any())
            decided["cut"] = c.tolist()
        elif o.limit > 0 and loss_h.max() > o.limit + 1e-9:
            new, event = want, "cut"  # a scenario takes more than the limit on this week's weights
            cut_weeks += 1
        elif np.abs(want[:3] - h[:3]).max() > BAND:
            new, event = want, "adjust"  # the target moved away: the trend's positions, the control, the drift
            adjust_weeks += 1
        else:
            new = h
        worst_after[t] = float(scen.losses(new[:3], moves).max())
        if event and log:
            g = int(np.argmax(loss_h))
            rows.append({"date": day, "kind": event, "scenario": scen.items[g]["label"], "loss_before": float(loss_h[g]),
                         "loss_after": worst_after[t], "cut": c.tolist(), "w": new.tolist(), "pos": bk.pos[t].tolist(),
                         "m": m})
        pending = REBALANCE_COST * float(np.abs(new[:3] - h[:3]).sum())
        if decided is not None and log:
            rows.append(decision_row(d, bk, t, decided, new, m, rows))
            rows[-1]["loss_after"] = worst_after[t]
        h = new
        held[t] = h
    xs = x[t0 + 1:]
    days = d.dates[t0 + 1:]
    out = {"t0": t0, "days": days, "x": xs, "held": held[t0:], "cut_weeks": cut_weeks, "adjust_weeks": adjust_weeks,
           "binding": binding,
           "rebalances": sum(1 for t in range(t0, W) if t in ends or t == t0), "worst_after": worst_after[t0:]}
    if log:
        if o.events and o.equity != "mcftr":
            for sale in (d.sales or {}).get(o.equity, []):
                w = sale["week"]
                if t0 < w < W:
                    rows.append({"date": d.dates[w], "kind": "event", "ticker": sale["ticker"],
                                 "name": d.names.get(sale["ticker"], sale["ticker"]), "event": events.KINDS[sale["kind"]][0],
                                 "news": sale["news"], "url": sale["url"], "share": sale["share"],
                                 "w": held[w].tolist(), "pos": bk.pos[w].tolist(), "cut": [1.0, 1.0, 1.0], "m": 1.0,
                                 "scenario": "", "loss_before": float(worst_after[w]), "loss_after": float(worst_after[w])})
            rows.sort(key=lambda r: (r["date"], r["kind"] != "event"))
        _fill_returns(rows, d, x)
        out["log"] = rows
    return out


def decide(d: Data, bk: Book, t: int, budget: np.ndarray, scen: Scenarios) -> dict:
    """The month's weights at week t: the risk budget (or the given shares) on the window, before the cap."""
    o = bk.o
    lo = max(1, t - WINDOW + 1)
    on = ready(bk, t) & (budget > 0)
    w = np.zeros(4)
    vol, rc = math.nan, np.zeros(3)
    idx = np.flatnonzero(on)
    if len(idx):
        X = bk.R[lo:t + 1][:, idx] - bk.R[lo:t + 1, 3:4]
        X = X[np.isfinite(X).all(axis=1)]
        cov = shrunk_cov(X)[0] * WEEKS + np.eye(len(idx)) * 1e-10
        if o.method == "risk":
            wi = budget_weights(cov, budget[idx])
            wi = wi * o.target_vol / math.sqrt(float(wi @ cov @ wi))
            if wi.sum() > 1:
                wi = wi / wi.sum()
        else:
            wi = budget[idx].copy()
        w[idx] = wi
        vol = math.sqrt(float(wi @ cov @ wi))
        rc[idx] = contributions(cov, wi)
    w[3] = 1 - w[:3].sum()
    b_eq = max(1.0, beta(bk.R[lo:t + 1, 0], d.mkt[lo:t + 1, 0])) if bk.o.equity != "mcftr" else 1.0
    b_bd = max(1.0, beta(bk.R[lo:t + 1, 1], d.mkt[lo:t + 1, 1])) if bk.o.bonds != "ofz" else 1.0
    moves = scen.sleeve_moves(bk.pos[t], b_eq, b_bd)
    loss = scen.losses(w[:3], moves)
    g = int(np.argmax(loss))
    return {"w": w, "vol": vol, "rc": rc, "betas": (b_eq, b_bd), "moves": moves, "worst": float(loss[g]),
            "scenario": scen.items[g]["label"], "cut": [1.0, 1.0, 1.0], "prio": np.maximum(rc, 0.0) + 1e-6}


def decision_row(d: Data, bk: Book, t: int, dec: dict, new: np.ndarray, m: float, rows: list[dict]) -> dict:
    prev = next((r for r in reversed(rows) if r["kind"] == "rebalance"), None)
    now = bk.picks.get(t, [])
    before = prev["picks"] if prev else []
    return {"date": d.dates[t], "kind": "rebalance", "budget_w": dec["w"].tolist(), "vol": dec["vol"],
            "rc": dec["rc"].tolist(), "scenario": dec["scenario"], "loss_before": dec["worst"], "cut": dec["cut"],
            "m": m, "w": new.tolist(), "pos": bk.pos[t].tolist(), "betas": list(dec["betas"]), "picks": now,
            "added": sorted(set(now) - set(before)), "removed": sorted(set(before) - set(now)) if now else []}


def _fill_returns(rows: list[dict], d: Data, x: np.ndarray) -> None:
    """Each decision's realized return: the book's from that week to the next decision."""
    ix = {day: i for i, day in enumerate(d.dates)}
    for a, b in zip(rows, rows[1:] + [None]):
        i = ix[a["date"]]
        k = ix[b["date"]] if b else len(d.dates) - 1
        seg = x[i + 1:k + 1]
        a["next"] = float(np.prod(1 + seg[np.isfinite(seg)]) - 1) if k > i else None
        a["until"] = d.dates[k]


# ---------------------------------------------------------------------------- the report


def stats(x: np.ndarray, cash: np.ndarray, days: list[str]) -> dict:
    ok = np.isfinite(x)
    x, c = x[ok], np.nan_to_num(cash[ok])
    if len(x) < 10:
        return {}
    eq = np.cumprod(1 + x)
    dd = 1 - eq / np.maximum.accumulate(eq)
    years = len(x) / WEEKS
    ex = x - c
    m4 = np.array([np.prod(1 + x[i:i + 4]) - 1 for i in range(0, len(x) - 3)])
    end = int(np.argmax(dd))
    start = int(np.argmax(eq[:end + 1])) if end else 0
    dk = [dd_ for dd_, ok_ in zip(days, ok) if ok_]
    return {"cagr": float(eq[-1] ** (1 / years) - 1), "vol": float(x.std() * math.sqrt(WEEKS)),
            "sharpe": float(ex.mean() / ex.std() * math.sqrt(WEEKS)) if ex.std() > 0 else 0.0,
            "dd": float(dd.max()), "dd_from": dk[start], "dd_to": dk[end], "worst_week": float(x.min()),
            "worst_4w": float(m4.min()) if len(m4) else None, "years": years}


def years_table(days: list[str], series: dict[str, np.ndarray]) -> list[dict]:
    out: dict[str, dict] = {}
    for key, x in series.items():
        for dd_, v in zip(days, x):
            if np.isfinite(v):
                out.setdefault(dd_[:4], {}).setdefault(key, 1.0)
                out[dd_[:4]][key] *= 1 + v
    return [{"year": y, **{k: v - 1 for k, v in out[y].items()}} for y in sorted(out)]


def thin_idx(n: int, most: int = 700) -> list[int]:
    step = max(1, n // most)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return idx


def report(req: dict) -> dict:
    t_start = time.time()
    o = Opts.from_dict(req)
    d = data(o.cost)
    main = run(d, o, log=True)
    t0 = main["t0"]
    days = main["days"]
    cash = d.returns["cash"][t0 + 1:]
    variants = [("book", "портфель из блоков", o)]
    if o.limit > 0:
        variants.append(("no_cap", "без сценарного предела", replace(o, limit=0.0)))
    if o.equity != "mcftr":
        variants.append(("index", "акции — индекс MCFTR вместо отбора", replace(o, equity="mcftr")))
    if o.budget[2] > 0:
        variants.append(("no_trend", "без тренда бота", replace(o, budget=(o.budget[0], o.budget[1], 0.0))))
        if o.trend == "main":
            variants.append(("guard", "тренд — основной с защитой", replace(o, trend="main_guard")))
    if o.control:
        variants.append(("no_control", "без контроля просадки", replace(o, control=0)))
    if o.events and o.equity != "mcftr" and any(s_["week"] > t0 for s_ in (d.sales or {}).get(o.equity, [])):
        variants.append(("no_events", "без фильтра событий Мосбиржи", replace(o, events=False)))
    variants.append(("6040", "60/40: MCFTR и ОФЗ, доли каждый месяц",
                     replace(o, equity="mcftr", bonds="ofz", method="weights", budget=(0.6, 0.4, 0.0), limit=0.0, control=0)))
    rows, curves, worst = [], {}, {}
    for key, title, vo in variants:
        res = main if key == "book" else run(d, vo, t0=t0)
        worst[key] = res["worst_after"][1:]
        rows.append({"key": key, "title": title, "kind": "book", **stats(res["x"], cash, days),
                     "cut_weeks": res["cut_weeks"] / max(len(days), 1), "adjust_weeks": res["adjust_weeks"] / max(len(days), 1),
                     "binding": res["binding"] / max(res["rebalances"], 1),
                     "worst_scenario": float(np.max(res["worst_after"])),
                     "cash_share": float(res["held"][:, 3].mean()), "turnover": _turnover(res["held"])})
        curves[key] = res["x"]
    limits = []
    for L in sorted(set(LIMITS) | {o.limit}, key=lambda v: v or 9):
        res = main if L == o.limit else run(d, replace(o, limit=L), t0=t0)
        limits.append({"limit": L, **stats(res["x"], cash, days), "worst_scenario": float(np.max(res["worst_after"])),
                       "cash_share": float(res["held"][:, 3].mean()), "turnover": _turnover(res["held"])})
    alone = [(f"equity:{o.equity}", f"только {SLEEVE_TITLES['equity']}: {dict(EQUITY)[o.equity]}"),
             (f"bonds:{o.bonds}", f"только {SLEEVE_TITLES['bonds']}: {dict(BONDS)[o.bonds]}"),
             (f"trend:{o.trend}", f"только тренд: {dict(TRENDS)[o.trend]}"), ("cash", "только деньги (RUONIA)")]
    if o.equity != "mcftr":
        alone.insert(1, ("equity:mcftr", "только индекс MCFTR"))
    for key, title in alone:
        x = d.returns[key][t0 + 1:]
        rows.append({"key": key, "title": title, "kind": "sleeve", **stats(x, cash, days)})
        curves[key] = x
    keys = [f"equity:{o.equity}", f"bonds:{o.bonds}", f"trend:{o.trend}", "cash"]
    S = np.column_stack([d.returns[k][t0 + 1:] for k in keys])
    corr = np.corrcoef(np.nan_to_num(S[:, :3]), rowvar=False)
    idx = thin_idx(len(days))
    eq_curves = {k: np.cumprod(1 + np.nan_to_num(v))[idx].tolist() for k, v in curves.items()}
    dd_curves = {}
    for k in ("book", "no_cap", "6040", "equity:mcftr"):
        if k in curves:
            e = np.cumprod(1 + np.nan_to_num(curves[k]))
            dd_curves[k] = (-(1 - e / np.maximum.accumulate(e)))[idx].tolist()
    held = main["held"][1:]
    today = today_section(d, o, main)
    ex = curves["book"] - np.nan_to_num(cash)
    tests = {"book": sizing.significance(ex, WEEKS)}
    for k in ("6040", "no_cap", "index", "no_trend"):
        if k in curves:
            tests[k] = sizing.compare(ex, curves[k] - np.nan_to_num(cash), WEEKS)
    tests["book"] = {k: tests["book"][k] for k in ("sharpe", "years", "se", "low", "high", "t")}
    return {
        "meta": {"opts": o.as_dict(), "from": d.dates[t0], "to": days[-1], "weeks": len(days), "panel_to": d.panel_to,
                 "window": WINDOW, "min_weeks": MIN_WEEKS, "rebalance_cost": REBALANCE_COST, "notes": d.notes,
                 "events_from": d.events_from,
                 "sales": len([s_ for s_ in (d.sales or {}).get(o.equity, []) if s_["week"] > t0]) if o.events else 0,
                 "control": CONTROLS[o.control].name, "elapsed": 0.0,
                 "choices": {"equity": EQUITY, "bonds": BONDS, "trend": TRENDS,
                             "controls": [c.name for c in CONTROLS]},
                 "sleeves": [SLEEVE_TITLES[s] for s in SLEEVES], "markets": MARKETS},
        "rows": rows,
        "series": {"dates": [days[i] for i in idx], "equity": eq_curves, "drawdown": dd_curves,
                   "weights": held[idx].T.tolist(), "worst": worst["book"][idx].tolist(),
                   "worst_no_cap": worst["no_cap"][idx].tolist() if "no_cap" in worst else None},
        "years": years_table(days, {"book": curves["book"], "6040": curves["6040"],
                                    "mcftr": d.returns["equity:mcftr"][t0 + 1:], "cash": cash}),
        "tests": tests,
        "limits": limits,
        "corr": {"labels": [SLEEVE_TITLES[s] for s in SLEEVES[:3]], "values": corr.tolist()},
        "log": list(reversed(main["log"])),
        "today": today,
        "elapsed": time.time() - t_start,
    }


def _turnover(held: np.ndarray) -> float:
    """One-way sleeve turnover a year."""
    if len(held) < 2:
        return 0.0
    return float(np.abs(np.diff(held[:, :3], axis=0)).sum() / 2 / (len(held) / WEEKS))


def today_section(d: Data, o: Opts, main: dict) -> dict:
    bk = assemble(d, o)
    t = len(d.dates) - 1
    w = main["held"][-1]
    last = next(r for r in reversed(main["log"]) if r["kind"] == "rebalance")
    scen = Scenarios(d, "9999")
    moves = scen.sleeve_moves(bk.pos[t], *last["betas"])
    contrib = -(moves * w[None, :3])  # S x 3 loss contributions
    total = contrib.sum(axis=1)
    rows = []
    for g, s in enumerate(scen.items):
        sel = np.flatnonzero(scen.group == g)
        k = sel[int(np.argmax(total[sel]))]
        rows.append({"label": s["label"], "kind": s["kind"], "to": s["to"], "loss": float(total[k]),
                     "sleeves": contrib[k].tolist(), "moves": scen.V[k].tolist()})
    rows.sort(key=lambda r: -r["loss"])
    form = max((k for k in bk.picks if k <= t), default=None)
    tickers = bk.picks.get(form, []) if form is not None else []
    try:
        status = events.check(tickers) if tickers else {}
    except Exception:  # noqa: BLE001
        status = {}
    sold_now = {s_["ticker"] for s_ in (d.sales or {}).get(o.equity, []) if form is not None and s_["week"] > form} \
        if o.events else set()
    picks = [{"ticker": tk, "name": d.names.get(tk, tk), "status": status.get(tk, {}).get("status", "ok"),
              "sold": tk in sold_now,
              "events": status.get(tk, {}).get("events", [])[:3]} for tk in tickers]
    latest = main["log"][-1]
    return {"date": d.dates[t], "w": w.tolist(), "budget": last["budget_w"], "decided": last["date"],
            "latest": latest["date"], "latest_kind": latest["kind"], "pos": bk.pos[t].tolist(),
            "scenarios": rows, "limit": o.limit, "picks": picks, "picked": d.dates[form] if form is not None else None,
            "betas": last["betas"]}
