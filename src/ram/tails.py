"""Tails: extreme value theory (peaks over threshold, generalized Pareto by maximum likelihood), the Hill estimator,
VaR and ES against the normal distribution and the history, the loss exceeded once in N years.

  G(y) = 1 - (1 + xi y / beta)^(-1/xi),  y = X - u > 0
  VaR_q = u + beta/xi * (((1 - q) / p_u)^(-xi) - 1),   ES_q = (VaR_q + beta - xi u) / (1 - xi)
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats as sst


def gpd_tail(losses: np.ndarray, q: float = 0.95) -> tuple[float, float, float, float]:
    """(threshold u, share of the observations beyond it, shape xi, scale beta)."""
    losses = losses[np.isfinite(losses)]
    u = float(np.quantile(losses, q))
    excess = losses[losses > u] - u
    if len(excess) < 10 or excess.std() == 0:
        return u, len(excess) / max(len(losses), 1), math.nan, math.nan
    xi, _, beta = sst.genpareto.fit(excess, floc=0)
    return u, len(excess) / len(losses), float(xi), float(beta)


def hill(x: np.ndarray, k: int) -> float:
    """Hill's tail index (xi = 1/alpha) of the k largest positive values."""
    x = np.sort(x[np.isfinite(x) & (x > 0)])[::-1]
    if len(x) <= k or k < 5:
        return math.nan
    return float(np.mean(np.log(x[:k])) - math.log(x[k]))


def hill_curve(x: np.ndarray, ks: list[int]) -> list[float | None]:
    out = []
    for k in ks:
        v = hill(x, k)
        out.append(None if not math.isfinite(v) else round(v, 4))
    return out


def tail_numbers(x: np.ndarray, per_year: float) -> dict:
    """VaR, ES and the once-in-N-years loss of the series x (returns; losses are -x), EVT against normal and history."""
    x = x[np.isfinite(x)]
    losses = -x
    u, pu, xi, beta = gpd_tail(losses)
    mu, sd = float(x.mean()), float(x.std())

    def var(q: float) -> float:
        if not math.isfinite(xi):
            return math.nan
        if abs(xi) < 1e-9:
            return u - beta * math.log((1 - q) / pu)
        return u + beta / xi * (((1 - q) / pu) ** -xi - 1)

    def es(q: float) -> float:
        return (var(q) + beta - xi * u) / (1 - xi) if math.isfinite(xi) and xi < 1 else math.nan

    out: dict = {"xi": xi, "beta": beta, "u": u, "pu": pu, "n": len(x), "mean": mu, "sd": sd,
                 "kurt": float(sst.kurtosis(x)) if len(x) > 3 else math.nan}
    rows = []
    for q in (0.95, 0.99, 0.999):
        z = sst.norm.ppf(q)
        hist_var = float(np.quantile(losses, q))
        tail = losses[losses >= hist_var]
        rows.append({"q": q,
                     "var": [var(q), -mu + z * sd, hist_var],
                     "es": [es(q), -mu + sd * sst.norm.pdf(z) / (1 - q), float(tail.mean()) if len(tail) else math.nan]})
    out["levels"] = rows
    once = []
    for years in (1, 5, 10, 20, 50):
        q = 1 - 1 / (years * per_year)
        once.append({"years": years, "evt": var(q), "normal": -mu + sst.norm.ppf(q) * sd})
    out["once"] = once
    return out


def survival(x: np.ndarray, points: int = 160) -> dict:
    """Exceedance probability of losses: the history (largest 10%), the GPD fit and the normal, for a log-scale chart."""
    x = x[np.isfinite(x)]
    losses = np.sort(-x)[::-1]
    n = len(losses)
    top = losses[: max(20, n // 10)]
    step = max(1, len(top) // points)
    emp = [[float(top[i]), (i + 1) / n] for i in range(0, len(top), step)]
    u, pu, xi, beta = gpd_tail(-x)
    mu, sd = float(x.mean()), float(x.std())
    hi = float(top[0]) * 1.6
    grid = np.linspace(max(u, 0.0), hi, 80)
    gpd = []
    if math.isfinite(xi):
        for g in grid:
            y = g - u
            base = 1 + xi * y / beta
            p = pu * (base ** (-1 / xi) if abs(xi) > 1e-9 and base > 0 else math.exp(-y / beta) if abs(xi) <= 1e-9 else 0.0)
            if p > 0:
                gpd.append([float(g), float(p)])
    normal = [[float(g), float(sst.norm.sf((g + mu) / sd))] for g in grid if sst.norm.sf((g + mu) / sd) > 1e-9]
    return {"empirical": emp, "gpd": gpd, "normal": normal, "u": u}


def histogram(x: np.ndarray, bins: int = 60) -> dict:
    x = x[np.isfinite(x)]
    lo, hi = np.quantile(x, [0.001, 0.999])
    counts, edges = np.histogram(np.clip(x, lo, hi), bins=bins, range=(lo, hi))
    width = edges[1] - edges[0]
    mu, sd = float(x.mean()), float(x.std())
    centers = (edges[:-1] + edges[1:]) / 2
    normal = len(x) * width * sst.norm.pdf(centers, mu, sd)
    return {"centers": [float(c) for c in centers], "counts": [int(c) for c in counts], "normal": [float(v) for v in normal]}


def asset_tails(r: np.ndarray) -> dict:
    """Tail index of falls and rises (GPD and Hill at 5%), kurtosis, skew."""
    r = r[np.isfinite(r) & (r != 0)]
    if len(r) < 200:
        return {"xi_down": math.nan, "xi_up": math.nan, "hill_down": math.nan, "hill_up": math.nan,
                "kurt": math.nan, "skew": math.nan, "n": len(r)}
    k = max(10, len(r) // 20)
    return {"xi_down": gpd_tail(-r)[2], "xi_up": gpd_tail(r)[2], "hill_down": hill(-r, k), "hill_up": hill(r, k),
            "kurt": float(sst.kurtosis(r)), "skew": float(sst.skew(r)), "n": len(r)}
