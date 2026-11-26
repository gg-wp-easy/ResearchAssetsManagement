"""The whole study of a basket, as one JSON-ready dict (the site's /api/study and `ram study`)."""
from __future__ import annotations

import math
import time
from dataclasses import replace

import numpy as np

from . import allocation, bootstrap, regimes, scenarios, sizing, tails
from .assets import AssetSpec, Basket, build, weekly
from .metrics import drawdown, equity, perf, period_returns, thin, weekly_t
from .rule import CONTROLS, Control, Params, Signal, full_size_today, independent, multipliers, signal, simulate, weights_today

LOOKBACK_GRID: list[tuple[str, tuple[int, ...]]] = [("10", (10,)), ("20", (20,)), ("40", (40,)), ("60", (60,)),
                                                    ("120", (120,)), ("250", (250,)), ("20+40+60", (20, 40, 60))]


def parse(req: dict) -> tuple[list[AssetSpec], Params, Control, dict]:
    specs = [AssetSpec.from_dict(a) for a in req.get("assets", [])]
    if not specs:
        raise ValueError("добавьте хотя бы один актив")
    if len(specs) > 30:
        raise ValueError("не больше 30 активов в корзине")
    params = Params.from_dict(req.get("params", {}))
    c = req.get("control", 0)
    control = CONTROLS[int(c)] if isinstance(c, (int, float)) else Control.from_dict(c)
    opts = {"start": req.get("start"), "end": req.get("end"), "period": req.get("period", "common"),
            "history_from": req.get("history_from"), "money_share": float(req.get("money_share", 0.5)),
            "windows": req.get("windows", []), "bootstrap_paths": int(req.get("bootstrap_paths", 4000))}
    return specs, params, control, opts


def first_ok(sig: Signal) -> np.ndarray:
    has = sig.ok.any(axis=0)
    idx = np.argmax(sig.ok, axis=0)
    return np.where(has, idx, -1)


def stats_start(b: Basket, sig: Signal, opts: dict) -> int:
    starts = first_ok(sig)
    if (starts < 0).all():
        raise ValueError("ни по одному активу не хватает истории для правила (нужно больше 60 дней и окно тренда)")
    valid = starts[starts >= 0]
    s0 = int(valid.max() if opts["period"] == "common" else valid.min())
    if opts["start"]:
        s0 = max(s0, b.index_of(opts["start"]))
    if s0 >= len(b.dates) - 60:
        raise ValueError("общий период слишком короткий: выберите «с начала каждого актива» или уберите короткий актив")
    return s0


def run_study(req: dict) -> dict:
    t0 = time.time()
    specs, p, control, opts = parse(req)
    b = build(specs, opts["history_from"], opts["end"])
    sig = signal(b, p)
    s0 = stats_start(b, sig, opts)
    days = b.dates[s0:]
    ppy = b.ppy
    run = simulate(b, p, control, sig)
    base = run if control.kind == "none" else simulate(b, p, CONTROLS[0], sig)
    p_hold = replace(p, signal="hold")
    sig_hold = signal(b, p_hold)
    hold = simulate(b, p_hold, CONTROLS[0], sig_hold)
    x, xh = run.x[s0:], hold.x[s0:]
    wdays, W = weekly(b)
    wk0 = next((k for k, d in enumerate(wdays) if d >= days[0]), 0)
    book_w = _weekly_of(b.dates, run.x, wdays)
    out = {
        "meta": {"assets": b.info, "warnings": b.warnings, "params": p.as_dict(), "control": control.__dict__,
                 "period": {"from": days[0], "to": days[-1], "years": len(days) / ppy, "mode": opts["period"],
                            "calendar_from": b.dates[0]},
                 "ppy": ppy, "labels": b.labels},
        "overview": overview(b, p, sig, s0, W[wk0:]),
        "rule": rule_section(b, p, run, hold, sig, s0),
        "crises": scenarios.crisis_table(b, run.x, run.pos, s0, scenarios.WINDOWS + [tuple(w) for w in opts["windows"]]),
        "scenarios": scenario_section(b, p, opts),
        "tails": tail_section(b, x, s0),
        "drawdown": drawdown_section(b, p, sig, s0, base, control, opts["bootstrap_paths"]),
        "regimes": regimes.regimes(wdays[wk0:], W[wk0:], book_w[wk0:], b.labels),
        "allocation": allocation_section(wdays, W, wk0, book_w, _weekly_of(b.dates, hold.x, wdays), b.labels),
        "sizing": {"kelly": sizing.kelly(x, ppy), "significance": sizing.significance(x, ppy),
                   "vs_hold": sizing.compare(x, xh, ppy),
                   "vs_base": sizing.compare(x, base.x[s0:], ppy) if base is not run else None},
    }
    out["meta"]["elapsed"] = time.time() - t0
    return clean(out)


def _weekly_of(dates: list[str], x: np.ndarray, wdays: list[str]) -> np.ndarray:
    """Compound the daily series into the weeks ending on `wdays` (week ends taken from the same calendar)."""
    out, k = np.zeros(len(wdays)), 0
    for d, v in zip(dates, x):
        while k < len(wdays) - 1 and d > wdays[k]:
            k += 1
        out[k] = (1 + out[k]) * (1 + v) - 1
    return out


def overview(b: Basket, p: Params, sig: Signal, s0: int, W: np.ndarray) -> dict:
    full, s = full_size_today(b, p)
    w_now = weights_today(b, p, s)
    rows = []
    for j in range(b.n):
        r = b.R[s0:, j]
        ok = np.isfinite(r)
        own_days = [d for d, k in zip(b.dates[s0:], ok) if k]
        st = perf(r[ok], own_days, ppy_own(own_days, b.ppy)) if ok.sum() > 30 else {}
        t = tails.asset_tails(b.R[:, j])
        rows.append({"label": b.labels[j], **{k: st.get(k) for k in ("cagr", "vol", "sharpe", "dd", "worst_day", "worst_day_date")},
                     **t, "vol_now": float(s[j] * math.sqrt(b.ppy)) if np.isfinite(s[j]) else None,
                     "w_now": float(w_now[j]), "full_now": float(full[j]) if np.isfinite(full[j]) else None,
                     "first": b.info[j]["first"], "last": b.info[j]["last"]})
    every = max(1, (len(b.dates) - s0) // 1200)
    base = []
    for j in range(b.n):
        col = b.E[s0:, j]
        first = np.flatnonzero(np.isfinite(col))
        base.append(col / col[first[0]] if len(first) else col)
    curves = thin(b.dates[s0:], *base, every=every)
    corr = {"labels": b.labels, "full": _corr(W), "last_year": _corr(W[-52:])}
    return {"assets": rows, "curves": curves, "corr": corr}


def ppy_own(days: list[str], fallback: float) -> float:
    from .assets import years_between
    if len(days) < 30:
        return fallback
    return (len(days) - 1) / years_between(days[0], days[-1])


def _corr(W: np.ndarray) -> list[list[float | None]]:
    N = W.shape[1]
    out = [[None] * N for _ in range(N)]
    for a in range(N):
        for c in range(N):
            ok = np.isfinite(W[:, a]) & np.isfinite(W[:, c])
            if ok.sum() >= 20 and W[ok, a].std() > 0 and W[ok, c].std() > 0:
                out[a][c] = float(np.corrcoef(W[ok, a], W[ok, c])[0, 1])
    return out


def rule_section(b: Basket, p: Params, run, hold, sig: Signal, s0: int) -> dict:
    days = b.dates[s0:]
    x, xh = run.x[s0:], hold.x[s0:]
    every = max(1, len(days) // 1500)
    years_b = period_returns(x, days, 4)
    years_h = period_returns(xh, days, 4)
    contrib = {}
    for j in range(b.n):
        for d, v in zip(days, run.pnl[s0:, j]):
            contrib.setdefault(d[:4], np.zeros(b.n))[j] += v
    year_rows = [{"year": y, "book": years_b[y], "hold": years_h.get(y), "assets": contrib[y].round(5).tolist(),
                  "costs": float(run.costs[s0:][[d[:4] == y for d in days]].sum())} for y in sorted(years_b)]
    months = period_returns(x, days, 7)
    worst_days = np.argsort(x)[:10]
    pos_every = max(1, len(days) // 600)
    positions = thin(days, *[run.pos[s0:, j] for j in range(b.n)], run.m[s0:], every=pos_every)
    totals = run.pnl[s0:].sum(axis=0) / (len(days) / b.ppy)
    heat = lookback_heat(b, p, s0)
    return {
        "book": perf(x, days, b.ppy), "hold": perf(xh, days, b.ppy),
        "vs_hold_t": weekly_t(days, x - xh),
        "equity": thin(days, equity(x), equity(xh), -drawdown(x), -drawdown(xh), every=every),
        "years": year_rows,
        "worst_months": [{"month": k, "r": v} for k, v in sorted(months.items(), key=lambda kv: kv[1])[:6]],
        "worst_days": [{"date": days[i], "r": float(x[i]), "assets": run.pnl[s0 + i].round(5).tolist()} for i in worst_days],
        "positions": positions,
        "per_asset_year": totals.tolist(),
        "turnover": float(np.abs(np.diff(run.pos[s0:], axis=0)).sum() / (len(days) / b.ppy)),
        "costs_year": float(run.costs[s0:].sum() / (len(days) / b.ppy)),
        "lookbacks": heat,
    }


def lookback_heat(b: Basket, p: Params, s0: int) -> dict:
    """Sharpe of each asset traded alone by the rule with each window, and of the basket (no margin cap)."""
    cols = [name for name, _ in LOOKBACK_GRID] + ["держать"]
    rows = [[None] * len(cols) for _ in range(b.n + 1)]
    cagr = [[None] * len(cols) for _ in range(b.n + 1)]
    for k, (name, lbs) in enumerate(LOOKBACK_GRID + [("держать", (20,))]):
        q = replace(p, lookbacks=lbs, signal="hold" if name == "держать" else "trend")
        pnl = independent(b, q)[s0:]
        for j in range(b.n + 1):
            r = pnl.sum(axis=1) if j == b.n else pnl[:, j]
            live = r != 0
            if j < b.n:
                live = b.alive[s0:, j]
            r = r[live]
            if len(r) > 120 and r.std() > 0:
                rows[j][k] = float(r.mean() / r.std() * math.sqrt(b.ppy))
                cagr[j][k] = float(r.mean() * b.ppy)
    return {"columns": cols, "rows": b.labels + ["вся корзина"], "sharpe": rows, "mean": cagr,
            "current": "+".join(str(L) for L in p.lookbacks)}


def scenario_section(b: Basket, p: Params, opts: dict) -> dict:
    full, s = full_size_today(b, p)
    w = weights_today(b, p, s)
    risks = sorted({0.05, 0.075, 0.10, 0.20, 0.50, round(p.risk, 4)})
    return {
        "date": b.dates[-1],
        "risk": p.risk, "risks": risks,
        "vol_now": [float(v * math.sqrt(b.ppy)) if np.isfinite(v) else None for v in s],
        "sigma_day": [float(v) if np.isfinite(v) else None for v in s],
        "full": [float(v) if np.isfinite(v) else None for v in full],
        "weights": w.tolist(),
        "go": [sp.go for sp in b.specs], "short_cap": [sp.short_cap for sp in b.specs],
        "margin_cap": p.margin_cap, "money_share": opts["money_share"],
        "historical": scenarios.scenario_moves(b),
        "hypothetical": scenarios.default_hypothetical(b, s),
    }


def tail_section(b: Basket, x: np.ndarray, s0: int) -> dict:
    days = b.dates[s0:]
    wk = []
    for i in range(0, len(x) - 4, 5):
        wk.append(float(np.prod(1 + x[i:i + 5]) - 1))
    wk = np.array(wk)
    assets = []
    for j in range(b.n):
        t = tails.asset_tails(b.R[:, j])
        r = b.R[:, j]
        r = r[np.isfinite(r) & (r != 0)]
        k_grid = [k for k in (10, 20, 30, 50, 75, 100, 150, 200, 300, 400) if k < len(r) // 4]
        assets.append({"label": b.labels[j], **t, "hill_k": k_grid, "hill_down_curve": tails.hill_curve(-r, k_grid),
                       "hill_up_curve": tails.hill_curve(r, k_grid)})
    return {"day": tails.tail_numbers(x, b.ppy), "week": tails.tail_numbers(wk, b.ppy / 5),
            "survival": tails.survival(x), "histogram": tails.histogram(x), "assets": assets,
            "worst": [{"date": days[i], "r": float(x[i])} for i in np.argsort(x)[:5]]}


def drawdown_section(b: Basket, p: Params, sig: Signal, s0: int, base, chosen: Control, paths: int) -> dict:
    days = b.dates[s0:]
    controls = list(CONTROLS)
    if chosen not in controls:
        controls.append(chosen)
    xb = base.x[s0:]
    rows, curves = [], []
    every = max(1, len(days) // 800)
    for c in controls:
        r = base if c.kind == "none" else simulate(b, p, c, sig)
        x = r.x[s0:]
        st = perf(x, days, b.ppy)
        st["cut"] = float((r.m[s0:] < 1).mean())
        if c.kind != "none":
            st["vs_base"] = float((x - xb).mean() * b.ppy)
            st["t"] = weekly_t(days, x - xb)
        rows.append({"name": c.name, "control": c.__dict__, "stats": st, "chosen": c == chosen})
        curves.append(equity(x))
    odds_controls = [c for c in controls if not c.rolling]
    odds = bootstrap.drawdown_odds(xb, odds_controls, b.ppy, n=max(500, min(paths, 8000)))
    grid = np.linspace(0, 0.45, 91)
    mult = [{"name": c.name, "values": multipliers(c, grid).round(4).tolist()} for c in controls if c.kind != "none"]
    return {"rows": rows, "equity": thin(days, *curves, every=every), "odds": odds,
            "multipliers": {"dd": grid.round(4).tolist(), "curves": mult}}


def allocation_section(wdays: list[str], W: np.ndarray, wk0: int, book_w: np.ndarray, hold_w: np.ndarray,
                       labels: list[str]) -> dict:
    if W.shape[1] < 2:
        return {"error": "распределение капитала имеет смысл для двух и более активов"}
    wf = allocation.walk_forward(wdays, W)
    if "error" in wf:
        return wf
    start = max(wk0, wdays.index(wf["first"]))
    days = wdays[start:]
    rows, curves = [], []
    for m, title in allocation.METHODS:
        r = wf["returns"][m][start:]
        rows.append({"key": m, "title": title, **allocation.summary(days, r), "turnover": wf["turnover"][m],
                     "now": wf["history"][m][-1]["w"] if wf["history"][m] else None})
        curves.append(np.cumprod(1 + np.nan_to_num(r)))
    for key, title, r in (("book", "правило тренда (книга)", book_w[start:]),
                          ("hold", "держать с размером по волатильности", hold_w[start:])):
        rows.append({"key": key, "title": title, **allocation.summary(days, r), "turnover": None, "now": None})
        curves.append(np.cumprod(1 + r))
    every = max(1, len(days) // 600)
    hist = {m: wf["history"][m] for m in ("erc", "min_cvar", "max_sharpe")}
    return {"from": days[0], "to": days[-1], "window_weeks": 156, "hold_weeks": 13, "rows": rows, "labels": labels,
            "equity": thin(days, *curves, every=every), "history": hist}


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return round(v, 7) if math.isfinite(v) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o
