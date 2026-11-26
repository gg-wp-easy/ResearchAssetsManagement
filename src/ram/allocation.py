"""Strategic allocation of the capital between the assets (long only, fully invested), estimated walk-forward: on the
last `window` weeks, held for the next `hold` weeks, so every return in the result is out of sample.

- equal: 1/N;
- inverse volatility: w ~ 1/sigma;
- risk parity (equal risk contributions): w_i (Sigma w)_i the same for every asset;
- minimum variance: min w' Sigma w;
- minimum CVaR 95% (Rockafellar and Uryasev 2000, a linear program on the weeks of the window):
    min zeta + 1/((1 - a) S) sum_s u_s,  u_s >= -w' r_s - zeta,  u_s >= 0;
- maximum Sharpe (the mean-variance tangency on estimated means: shows how unstable estimated means are).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linprog, minimize

METHODS = [("equal", "поровну"), ("inv_vol", "обратно волатильности"), ("erc", "паритет риска"),
           ("min_var", "минимум дисперсии"), ("min_cvar", "минимум CVaR 95%"), ("max_sharpe", "максимум Шарпа (по оценкам)")]


def weights(method: str, X: np.ndarray) -> np.ndarray:
    """Weights from a window of weekly returns X (S x n, no NaN)."""
    S, n = X.shape
    if n == 1:
        return np.ones(1)
    cov = np.cov(X, rowvar=False) + np.eye(n) * 1e-10
    vol = np.sqrt(np.diag(cov))
    if method == "equal":
        return np.ones(n) / n
    if method == "inv_vol":
        w = 1 / vol
        return w / w.sum()
    if method == "erc":
        w = (1 / vol) / (1 / vol).sum()
        for _ in range(500):
            rc = w * (cov @ w)
            target = rc.mean()
            if np.max(np.abs(rc - target)) < 1e-10 * max(target, 1e-12):
                break
            w = w * (target / np.maximum(rc, 1e-18)) ** 0.5
            w = w / w.sum()
        return w
    bounds = [(0.0, 1.0)] * n
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    w0 = np.ones(n) / n
    if method == "min_var":
        res = minimize(lambda w: w @ cov @ w, w0, jac=lambda w: 2 * cov @ w, bounds=bounds, constraints=cons, method="SLSQP")
        return _clean(res.x if res.success else w0)
    if method == "max_sharpe":
        mu = X.mean(axis=0)
        if mu.max() <= 0:
            return _clean(weights("min_var", X))
        res = minimize(lambda w: -(mu @ w) / math.sqrt(max(w @ cov @ w, 1e-18)), w0, bounds=bounds, constraints=cons,
                       method="SLSQP")
        return _clean(res.x if res.success else w0)
    if method == "min_cvar":
        a = 0.95
        c = np.r_[np.zeros(n), 1.0, np.full(S, 1 / ((1 - a) * S))]
        A = np.hstack([-X, -np.ones((S, 1)), -np.eye(S)])  # -r_s w - zeta - u_s <= 0
        A_eq = np.r_[np.ones(n), 0.0, np.zeros(S)][None, :]
        res = linprog(c, A_ub=A, b_ub=np.zeros(S), A_eq=A_eq, b_eq=[1.0],
                      bounds=[(0, 1)] * n + [(None, None)] + [(0, None)] * S, method="highs")
        return _clean(res.x[:n] if res.success else w0)
    raise ValueError(method)


def _clean(w: np.ndarray) -> np.ndarray:
    w = np.clip(w, 0, None)
    return w / w.sum() if w.sum() > 0 else np.ones(len(w)) / len(w)


def walk_forward(days: list[str], W: np.ndarray, window: int = 156, hold: int = 13) -> dict:
    """Out-of-sample weekly returns of each method; at each rebalance only the assets with the whole window."""
    T, N = W.shape
    out = {m: np.full(T, np.nan) for m, _ in METHODS}
    history = {m: [] for m, _ in METHODS}
    turnover = {m: 0.0 for m, _ in METHODS}
    prev = {m: np.zeros(N) for m, _ in METHODS}
    first = None
    for t0 in range(window, T, hold):
        X = W[t0 - window:t0]
        cols = np.flatnonzero(np.isfinite(X).all(axis=0))
        if len(cols) == 0:
            continue
        if first is None:
            first = t0
        Xc = X[:, cols]
        block = W[t0:t0 + hold]
        for m, _ in METHODS:
            w = np.zeros(N)
            w[cols] = weights(m, Xc)
            turnover[m] += float(np.abs(w - prev[m]).sum())
            prev[m] = w
            history[m].append({"date": days[t0], "w": [round(float(v), 4) for v in w]})
            r = np.nan_to_num(block) @ w
            out[m][t0:t0 + hold] = r
    if first is None:
        return {"error": f"для распределения нужно больше {window} недель истории хотя бы у одного актива"}
    return {"first": days[first], "returns": out, "history": history,
            "turnover": {m: turnover[m] / max(len(history[m]) - 1, 1) for m in turnover}}


def summary(days: list[str], r: np.ndarray, per_year: float = 52) -> dict:
    ok = np.isfinite(r)
    x = r[ok]
    if len(x) < 10:
        return {}
    eq = np.cumprod(1 + x)
    dd = 1 - eq / np.maximum.accumulate(eq)
    sd = x.std()
    q = np.quantile(-x, 0.95)
    years = len(x) / per_year
    return {"cagr": float(eq[-1] ** (1 / years) - 1), "vol": float(sd * math.sqrt(per_year)),
            "sharpe": float(x.mean() / sd * math.sqrt(per_year)) if sd > 0 else 0.0, "dd": float(dd.max()),
            "worst_week": float(x.min()), "cvar95": float((-x)[-x >= q].mean())}
