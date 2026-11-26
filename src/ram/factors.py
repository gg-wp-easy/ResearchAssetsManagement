"""The factor lab of MOEX shares: does a characteristic known at a month's end order the shares' next-month returns?

Each month-end (the last weekly session of the month, see universe.py) the universe is the `top` most traded TQBR shares
(median daily value over the last 13 weeks, traded on the day). For each factor and month:

- IC: Spearman's correlation of the factor with the next month's total return across the universe;
  t(IC) = mean / sd * sqrt(months);
- quintiles: equal-weight portfolios of the fifths by the factor, Q5 the highest; Q5 - Q1 (long-short) and Q5 minus
  the universe's equal-weight return (long only - shorting Russian shares is limited); net of costs: one-way turnover of
  Q5 times two sides times the cost per side;
- Fama-MacBeth: each month an OLS of the returns on the factors' cross-sectional ranks (scaled to unit variance), the
  coefficients averaged over the months: the premium of one standard deviation of each factor net of the others.

Point in time: prices and dividends up to the date; a report counts from the day after smart-lab's publication date
(server-analytic-system's data: annual reports 2021-2025, so the report factors start in 2022). With K factors tried,
the best |t| of K pure-noise factors is about sqrt(2 ln K) - hence the Bonferroni bar and Harvey, Liu and Zhu's t > 3.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm, rankdata

from . import sas, sources, universe
from .assets import ffill_on

FACTORS = [
    # key, title, data, description, sign meaning
    ("mom", "моментум 12−1", "price", "доходность за 12 месяцев без последнего"),
    ("rev", "разворот месяца", "price", "минус доходность последнего месяца"),
    ("lowvol", "низкая волатильность", "price", "минус σ недельной доходности за год"),
    ("lowbeta", "низкая бета", "price", "минус бета к MCFTR за год"),
    ("illiq", "низкая ликвидность", "price", "минус логарифм дневного оборота"),
    ("dy", "дивидендная доходность", "dividends", "дивиденды за 12 месяцев / цена"),
    ("ep", "E/P", "reports", "чистая прибыль / капитализация"),
    ("bp", "B/P", "reports", "капитал / капитализация"),
    ("sp", "S/P", "reports", "выручка / капитализация"),
    ("fcfp", "FCF/P", "reports", "свободный денежный поток / капитализация"),
    ("roe", "ROE", "reports", "чистая прибыль / капитал"),
    ("lowlev", "низкий долг", "reports", "минус чистый долг / EBITDA"),
    ("size", "малая капитализация", "reports", "минус логарифм капитализации"),
]
TITLE = {k: t for k, t, _, _ in FACTORS}
MODELS = [
    ("price", "ценовые факторы", ["mom", "rev", "lowvol", "illiq"]),
    ("all", "все вместе", ["mom", "rev", "lowvol", "illiq", "dy", "ep", "bp", "roe", "size"]),
]
WEEKS_YEAR, WEEKS_MONTH = 52, 4


def month_ends(dates: list[str]) -> list[int]:
    return [i for i in range(len(dates)) if i == len(dates) - 1 or dates[i + 1][:7] != dates[i][:7]]


def class_tickers(page: str, traded: set[str]) -> tuple[str, str]:
    """(ordinary, preferred) tickers of a smart-lab company page (SBER -> SBER, SBERP; a page under a preferred share
    whose ordinary share trades: WTCMP -> WTCM, WTCMP), as server-analytic-system's snapshot.class_tickers."""
    if page.endswith("P") and page[:-1] in traded:
        return page[:-1], page
    return page, page + "P"


@dataclass
class Month:
    t: int  # the formation week in the panel
    u: int  # the week the month ends (the next formation)
    cols: np.ndarray  # universe columns
    fwd: np.ndarray  # next month's total return
    f: dict[str, np.ndarray]


def build_months(p: universe.Panel, start: str, top: int) -> tuple[list[Month], list[str]]:
    warnings: list[str] = []
    T, N = p.R.shape
    logg = np.log1p(np.nan_to_num(p.R))
    C = np.vstack([np.zeros(N), np.cumsum(logg, axis=0)])  # C[i + 1] - C[j + 1]: log return over weeks j+1..i
    cnt = np.vstack([np.zeros(N), np.cumsum(np.isfinite(p.R), axis=0)])
    present = np.isfinite(p.P)
    try:
        mc = sources.load("moex:index:MCFTR")
        m_px = ffill_on(mc.dates, mc.values, p.dates)
        M = np.r_[np.nan, m_px[1:] / m_px[:-1] - 1]
    except Exception as e:  # noqa: BLE001
        M = np.full(T, np.nan)
        warnings.append(f"MCFTR не загрузился ({e}): без беты")
    reps = sas.reports() or {}
    if not reps:
        warnings.append("нет отчётности server-analytic-system: факторы по отчётам не считаются")
    if not sas.dividends():
        warnings.append("нет дивидендов server-analytic-system: доходность без дивидендов, дивидендного фактора нет")
    col = {tk: j for j, tk in enumerate(p.tickers)}
    ends = month_ends(p.dates)
    months: list[Month] = []
    div_from = sas.DIVIDENDS_FROM
    for k in range(len(ends) - 1):
        t, u = ends[k], ends[k + 1]
        if p.dates[t] < start or t < WEEKS_YEAR:
            continue
        lo = t - 12
        seen = present[lo:t + 1].sum(axis=0)
        traded = (p.V[t] > 0) & present[t] & (seen >= 8)
        med = np.median(np.where(present[lo:t + 1], p.V[lo:t + 1], 0.0), axis=0)
        cand = np.flatnonzero(traded & (med > 0))
        cols = cand[np.argsort(-med[cand])][:top]
        if len(cols) < 20:
            continue
        fwd = np.expm1(C[u + 1, cols] - C[t + 1, cols])
        f: dict[str, np.ndarray] = {}
        a, b = t - WEEKS_YEAR, t - WEEKS_MONTH
        ok_m = (cnt[b + 1, cols] - cnt[a + 1, cols]) >= 40
        f["mom"] = np.where(ok_m, np.expm1(C[b + 1, cols] - C[a + 1, cols]), np.nan)
        ok_r = (cnt[t + 1, cols] - cnt[b + 1, cols]) >= 3
        f["rev"] = np.where(ok_r, -np.expm1(C[t + 1, cols] - C[b + 1, cols]), np.nan)
        win = p.R[t - WEEKS_YEAR + 1:t + 1][:, cols]
        n_ok = np.isfinite(win).sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            f["lowvol"] = np.where(n_ok >= 40, -np.nanstd(win, axis=0), np.nan)
            mw = M[t - WEEKS_YEAR + 1:t + 1]
            beta = np.full(len(cols), np.nan)
            for q in range(len(cols)):
                ok = np.isfinite(win[:, q]) & np.isfinite(mw)
                if ok.sum() >= 40 and mw[ok].var() > 0:
                    x, y = mw[ok], win[ok, q]
                    beta[q] = ((x - x.mean()) * (y - y.mean())).mean() / x.var()
            f["lowbeta"] = -beta
            f["illiq"] = -np.log(med[cols])
        if p.dates[a] >= div_from and p.covered.any():
            dsum = p.D[a + 1:t + 1, cols].sum(axis=0)
            f["dy"] = np.where(p.covered[cols], dsum / p.P[t, cols], np.nan)
        if reps:
            f.update(report_factors(p, t, cols, reps, col))
        months.append(Month(t=t, u=u, cols=cols, fwd=fwd, f=f))
    return months, warnings


def report_factors(p: universe.Panel, t: int, cols: np.ndarray, reps: dict, col: dict[str, int]) -> dict[str, np.ndarray]:
    day = p.dates[t]
    traded = {p.tickers[j] for j in np.flatnonzero(np.isfinite(p.P[t]))}
    out = {k: np.full(len(cols), np.nan) for k in ("ep", "bp", "sp", "fcfp", "roe", "lowlev", "size")}
    for q, j in enumerate(cols):
        ticker = p.tickers[j]
        rep = sas.report_as_of(reps.get(ticker, []), day)
        if rep is None:
            continue
        o, pr = class_tickers(rep.page or ticker, traded)
        price = {x: p.P[t, col[x]] for x in (o, pr) if x in col and np.isfinite(p.P[t, col[x]])}
        po, pp = price.get(o, price.get(pr)), price.get(pr, price.get(o))  # a class off the board at the other's price
        n_o, n_p = rep.get("number_of_shares"), rep.get("number_of_priv_shares")
        if po is None or not n_o > 0:
            continue
        cap = n_o * po + (n_p * pp if n_p > 0 and pp is not None else 0.0)
        own = rep.get("market_cap")
        if own > 0 and not 0.1 < cap / own < 10:  # a unit slip in smart-lab's share count
            continue
        ni, book = rep.get("net_income"), rep.get("net_assets", "book_value", "capital")
        rev, fcf = rep.get("revenue"), rep.get("fcf")
        nd, ebitda = rep.get("net_debt"), rep.get("ebitda")
        out["ep"][q] = ni / cap
        out["bp"][q] = book / cap
        out["sp"][q] = rev / cap if rev > 0 else math.nan
        out["fcfp"][q] = fcf / cap
        out["roe"][q] = ni / book if book > 0 else rep.get("roe") / 100
        out["lowlev"][q] = -nd / ebitda if ebitda > 0 and math.isfinite(nd) else math.nan
        out["size"][q] = -math.log(cap)
    return out


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx, ry = rankdata(x), rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return math.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def _t(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 2 and x.std(ddof=1) > 0 else math.nan


def evaluate(months: list[Month], dates: list[str], tickers: list[str], key: str, cost: float, min_names: int = 20) -> dict | None:
    rows = []
    prev: set[str] | None = None
    for m in months:
        if key not in m.f:
            continue
        f, r = m.f[key], m.fwd
        ok = np.isfinite(f) & np.isfinite(r)
        if ok.sum() < min_names:
            continue
        f, r, names = f[ok], r[ok], m.cols[ok]
        rank = rankdata(f)
        q = np.minimum(((rank - 1) * 5 / len(f)).astype(int), 4)
        qr = [float(r[q == g].mean()) if (q == g).any() else math.nan for g in range(5)]
        top = {tickers[j] for j in names[q == 4]}
        turn = 1 - len(top & prev) / len(top) if prev and top else 1.0
        prev = top
        ew = float(r.mean())
        rows.append({"date": dates[m.t], "end": dates[m.u], "ic": _spearman(f, r), "q": qr, "ew": ew, "n": int(ok.sum()),
                     "turn": turn})
    if len(rows) < 6:
        return None
    ic = np.array([x["ic"] for x in rows])
    Q = np.array([x["q"] for x in rows])
    ew = np.array([x["ew"] for x in rows])
    turn = np.array([x["turn"] for x in rows[1:]]) if len(rows) > 1 else np.zeros(1)
    ls, ex = Q[:, 4] - Q[:, 0], Q[:, 4] - ew
    net = ex - 2 * cost * np.r_[1.0, turn]
    cum = [np.cumprod(1 + np.nan_to_num(Q[:, g])).tolist() for g in range(5)] + [np.cumprod(1 + ew).tolist()]
    return {
        "key": key, "title": TITLE[key], "months": len(rows), "from": rows[0]["date"], "to": rows[-1]["date"],
        "names": float(np.mean([x["n"] for x in rows])),
        "ic": float(np.nanmean(ic)), "ic_t": _t(ic), "ic_hit": float(np.mean(ic[np.isfinite(ic)] > 0)),
        "q": (np.nanmean(Q, axis=0) * 12).tolist(), "ew": float(ew.mean() * 12),
        "ls": float(np.nanmean(ls) * 12), "ls_t": _t(ls), "ex": float(np.nanmean(ex) * 12), "ex_t": _t(ex),
        "net": float(np.nanmean(net) * 12), "net_t": _t(net), "turnover": float(turn.mean()),
        "series": {"dates": [x["date"] for x in rows], "ends": [x["end"] for x in rows], "ic": ic.tolist(), "cum": cum},
    }


def rank_z(x: np.ndarray) -> np.ndarray:
    r = rankdata(x)
    return (r - r.mean()) / r.std() if r.std() > 0 else np.zeros(len(x))


def fama_macbeth(months: list[Month], dates: list[str], keys: list[str]) -> dict | None:
    coefs, r2, used = [], [], []
    for m in months:
        if any(k not in m.f for k in keys):
            continue
        X = np.column_stack([m.f[k] for k in keys])
        ok = np.isfinite(X).all(axis=1) & np.isfinite(m.fwd)
        if ok.sum() < max(30, 3 * len(keys)):
            continue
        Z = np.column_stack([np.ones(ok.sum())] + [rank_z(X[ok, i]) for i in range(len(keys))])
        y = m.fwd[ok]
        b, *_ = np.linalg.lstsq(Z, y, rcond=None)
        res = y - Z @ b
        coefs.append(b[1:])
        r2.append(1 - res.var() / y.var() if y.var() > 0 else math.nan)
        used.append(dates[m.t])
    if len(coefs) < 6:
        return None
    B = np.array(coefs)
    return {"from": used[0], "to": used[-1], "months": len(used), "r2": float(np.nanmean(r2)),
            "rows": [{"key": k, "title": TITLE[k], "coef": float(B[:, i].mean() * 12), "t": _t(B[:, i])}
                     for i, k in enumerate(keys)]}


def correlations(months: list[Month], keys: list[str]) -> list[list[float | None]]:
    out: list[list[float | None]] = [[None] * len(keys) for _ in keys]
    for a in range(len(keys)):
        out[a][a] = 1.0
        for b in range(a + 1, len(keys)):
            vals = []
            for m in months:
                if keys[a] in m.f and keys[b] in m.f:
                    x, y = m.f[keys[a]], m.f[keys[b]]
                    ok = np.isfinite(x) & np.isfinite(y)
                    if ok.sum() >= 20:
                        vals.append(_spearman(x[ok], y[ok]))
            vals = [v for v in vals if math.isfinite(v)]
            if len(vals) >= 6:
                out[a][b] = out[b][a] = float(np.mean(vals))
    return out


def lab(start: str = "2015-01-01", top: int = 100, cost: float = 0.002) -> dict:
    t0 = time.time()
    p = universe.panel()
    months, warnings = build_months(p, start, top)
    if not months:
        raise ValueError("нет ни одного месяца с данными: начните позже или возьмите больше бумаг")
    results = [r for r in (evaluate(months, p.dates, p.tickers, k, cost) for k, *_ in FACTORS) if r]
    keys = [r["key"] for r in results]
    k = len(results)
    bonferroni = float(norm.ppf(1 - 0.025 / k)) if k else math.nan
    noise_max = float(norm.ppf((1 + 0.5 ** (1 / k)) / 2)) if k else math.nan
    ew = np.array([float(m.fwd[np.isfinite(m.fwd)].mean()) for m in months])
    u_dates = [p.dates[m.t] for m in months]
    try:
        mc = sources.load("moex:index:MCFTR")
        mcftr = (ffill_on(mc.dates, mc.values, [p.dates[m.u] for m in months])
                 / ffill_on(mc.dates, mc.values, [p.dates[m.t] for m in months]) - 1)
    except Exception:  # noqa: BLE001
        mcftr = np.full(len(months), np.nan)
    info = {key: (title, data, desc) for key, title, data, desc in FACTORS}
    for r in results:
        r["data"], r["desc"] = info[r["key"]][1], info[r["key"]][2]
        r["sig"] = bool(abs(r["ic_t"]) > bonferroni) if math.isfinite(r["ic_t"]) else False
    lost = np.mean([float((~np.isfinite(p.P[min(m.t + 5, len(p.dates) - 1), m.cols])).mean()) for m in months])
    return {
        "meta": {"from": u_dates[0], "to": u_dates[-1], "months": len(months), "top": top, "cost": cost, "start": start,
                 "panel_from": p.dates[0], "panel_to": p.dates[-1], "tickers": len(p.tickers), "sas": bool(sas.sas_dir()),
                 "warnings": warnings + p.notes, "elapsed": 0.0, "lost_share": float(lost)},
        "universe": {"dates": u_dates, "ends": [p.dates[m.u] for m in months], "count": [len(m.cols) for m in months],
                     "median_value": [float(np.median(p.V[m.t, m.cols])) for m in months],
                     "ew": np.cumprod(1 + ew).tolist(), "mcftr": np.cumprod(1 + np.nan_to_num(mcftr)).tolist(),
                     "ew_year": float(ew.mean() * 12), "mcftr_year": float(np.nanmean(mcftr) * 12)},
        "factors": results,
        "fm": [dict(key=mk, title=title, **fm) for mk, title, ks in MODELS
               if (fm := fama_macbeth(months, p.dates, [x for x in ks if x in keys]))],
        "corr": {"keys": keys, "titles": [TITLE[x] for x in keys], "values": correlations(months, keys)},
        "testing": {"k": k, "bonferroni": bonferroni, "hlz": 3.0, "noise_max": noise_max},
        "elapsed": time.time() - t0,
    }
