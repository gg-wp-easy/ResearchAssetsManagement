"""Performance of a daily return series (share of capital)."""
from __future__ import annotations

import math
from datetime import date

import numpy as np


def equity(x: np.ndarray) -> np.ndarray:
    return np.cumprod(1 + x)


def drawdown(x: np.ndarray) -> np.ndarray:
    eq = equity(x)
    peak = np.maximum.accumulate(eq)
    return 1 - eq / peak


def period_returns(x: np.ndarray, days: list[str], width: int) -> dict[str, float]:
    """Return of each calendar month (width 7) or year (width 4)."""
    eq = equity(x)
    last: dict[str, float] = {}
    first: dict[str, float] = {}
    for i, d in enumerate(days):
        k = d[:width]
        if k not in first:
            first[k] = eq[i - 1] if i else 1.0
        last[k] = eq[i]
    return {k: last[k] / first[k] - 1 for k in last}


def perf(x: np.ndarray, days: list[str], ppy: float) -> dict:
    """Annual growth, volatility, Sharpe (on excess returns), drawdown and the worst periods."""
    if len(x) < 2:
        return {}
    eq = equity(x)
    dd = drawdown(x)
    years = max(len(x) / ppy, 1e-9)
    sd = float(x.std())
    win = int(round(ppy))
    yr = np.array([eq[i] / eq[i - win] - 1 for i in range(win, len(eq))]) if len(eq) > win else np.array([eq[-1] - 1])
    months = period_returns(x, days, 7)
    under, longest = 0, 0
    for v in dd:
        under = under + 1 if v > 0.001 else 0
        longest = max(longest, under)
    cagr = float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 else -1.0
    mdd = float(dd.max())
    worst_day = int(np.argmin(x))
    mdd_end = int(np.argmax(dd))
    mdd_start = int(np.argmax(eq[: mdd_end + 1])) if mdd_end else 0
    return {
        "cagr": cagr,
        "mean": float(x.mean() * ppy),
        "vol": sd * math.sqrt(ppy),
        "sharpe": float(x.mean() / sd * math.sqrt(ppy)) if sd > 0 else 0.0,
        "dd": mdd,
        "dd_from": days[mdd_start],
        "dd_to": days[mdd_end],
        "calmar": cagr / mdd if mdd > 0 else 0.0,
        "worst_day": float(x[worst_day]),
        "worst_day_date": days[worst_day],
        "worst_month": float(min(months.values())) if months else 0.0,
        "worst_month_date": min(months, key=months.get) if months else "",
        "worst_year": float(yr.min()),
        "best_year": float(yr.max()),
        "underwater": longest / ppy,
        "skew": float(((x - x.mean()) ** 3).mean() / sd ** 3) if sd > 0 else 0.0,
        "kurt": float(((x - x.mean()) ** 4).mean() / sd ** 4 - 3) if sd > 0 else 0.0,
        "years": years,
        "from": days[0],
        "to": days[-1],
    }


def weekly_sum(days: list[str], x: np.ndarray) -> np.ndarray:
    weeks: dict[tuple, float] = {}
    for d, v in zip(days, x):
        y, w, _ = date.fromisoformat(d).isocalendar()
        weeks[(y, w)] = weeks.get((y, w), 0.0) + float(v)
    return np.array(list(weeks.values()))


def weekly_t(days: list[str], diff: np.ndarray) -> float:
    """t-statistic of the mean of a daily difference, summed by weeks (less sensitive to the daily noise)."""
    w = weekly_sum(days, diff)
    return float(w.mean() / (w.std(ddof=1) / math.sqrt(len(w)))) if len(w) > 2 and w.std() > 0 else 0.0


def thin(days: list[str], *cols: np.ndarray, every: int = 1) -> dict:
    """Every `every`-th point of the series (and the last), for charts."""
    idx = list(range(0, len(days), every))
    if idx and idx[-1] != len(days) - 1:
        idx.append(len(days) - 1)
    return {"dates": [days[i] for i in idx], "values": [[_num(c[i]) for i in idx] for c in cols]}


def _num(v) -> float | None:
    v = float(v)
    return round(v, 6) if math.isfinite(v) else None
