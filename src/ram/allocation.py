"""Strategic allocation of the capital between the assets (long only, fully invested), estimated walk-forward: on the
last `window` weeks, held for the next `hold` weeks, so every return in the result is out of sample.

- equal: 1/N;
- inverse volatility: w ~ 1/sigma;
- risk parity (equal risk contributions): w_i (Sigma w)_i the same for every asset;
- minimum variance: min w' Sigma w;
- minimum CVaR 95% (Rockafellar and Uryasev 2000, a linear program on the weeks of the window):
    min zeta + 1/((1 - a) S) sum_s u_s,  u_s >= -w' r_s - zeta,  u_s >= 0;
- maximum Sharpe (the mean-variance tangency on estimated means: shows how unstable estimated means are);
- hierarchical risk parity (Lopez de Prado 2016): the assets ordered by a single-linkage tree of the correlation
  distance d = sqrt((1 - rho) / 2), the weight split down the tree in inverse proportion to each half's variance - no
  matrix inversion, so a noisy covariance hurts it less;
- given weights (a portfolio from elsewhere, e.g. server-analytic-system's), renormalized over the assets with history.

The covariance is the sample one or Ledoit and Wolf's shrinkage to the constant correlation ("Honey, I shrunk the
sample covariance matrix", 2004): the variances stay, the correlations move toward their average by the intensity that
minimizes the expected squared error - with few weeks and many assets the sample correlations are mostly noise.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.optimize import linprog, minimize
from scipy.spatial.distance import squareform

METHODS = [("equal", "поровну"), ("inv_vol", "обратно волатильности"), ("erc", "паритет риска"),
           ("hrp", "иерархический паритет риска (HRP)"), ("min_var", "минимум дисперсии"),
           ("min_cvar", "минимум CVaR 95%"), ("max_sharpe", "максимум Шарпа (по оценкам)")]
GIVEN = ("given", "заданные веса")
COVS = ("shrunk", "sample")


def shrunk_cov(X: np.ndarray) -> tuple[np.ndarray, float]:
    """(Ledoit-Wolf covariance shrunk to the constant correlation, the shrinkage intensity in [0, 1]); X is S x n.
    A port of Ledoit and Wolf's covCor.m."""
    t, n = X.shape
    x = X - X.mean(axis=0)
    sample = x.T @ x / t
    var = np.diag(sample).copy()
    sd = np.sqrt(var)
    if n < 2 or not (sd > 0).all():
        return sample, 0.0
    outer = np.outer(sd, sd)
    r_bar = ((sample / outer).sum() - n) / (n * (n - 1))
    prior = r_bar * outer
    np.fill_diagonal(prior, var)
    y = x ** 2
    phi_mat = y.T @ y / t - 2 * (x.T @ x) * sample / t + sample ** 2
    phi = phi_mat.sum()
    term1 = (x ** 3).T @ x / t
    help_ = x.T @ x / t
    term2 = np.diag(help_)[:, None] * sample
    term3 = help_ * var[:, None]
    term4 = var[:, None] * sample
    theta = term1 - term2 - term3 + term4
    np.fill_diagonal(theta, 0.0)
    rho = np.trace(phi_mat) + r_bar * ((np.outer(1 / sd, sd)) * theta).sum()
    gamma = float(((sample - prior) ** 2).sum())
    delta = float(max(0.0, min(1.0, (phi - rho) / gamma / t))) if gamma > 0 else 1.0
    return delta * prior + (1 - delta) * sample, delta


def covariance(X: np.ndarray, kind: str = "shrunk") -> np.ndarray:
    n = X.shape[1]
    cov = shrunk_cov(X)[0] if kind == "shrunk" else np.cov(X, rowvar=False)
    return np.atleast_2d(cov) + np.eye(n) * 1e-10


def hrp(cov: np.ndarray) -> np.ndarray:
    n = len(cov)
    if n == 1:
        return np.ones(1)
    sd = np.sqrt(np.diag(cov))
    corr = np.clip(cov / np.outer(sd, sd), -1, 1)
    dist = np.sqrt(np.clip((1 - corr) / 2, 0, None))
    np.fill_diagonal(dist, 0.0)
    order = list(leaves_list(linkage(squareform(dist, checks=False), method="single")))
    w = np.ones(n)
    clusters = [order]
    while clusters:
        nxt = []
        for c in clusters:
            if len(c) < 2:
                continue
            half = len(c) // 2
            a, b = c[:half], c[half:]
            va, vb = _cluster_var(cov, a), _cluster_var(cov, b)
            alpha = 1 - va / (va + vb)
            w[a] *= alpha
            w[b] *= 1 - alpha
            nxt += [a, b]
        clusters = nxt
    return w / w.sum()


def _cluster_var(cov: np.ndarray, idx: list[int]) -> float:
    sub = cov[np.ix_(idx, idx)]
    ivp = 1 / np.diag(sub)
    ivp /= ivp.sum()
    return float(ivp @ sub @ ivp)


def weights(method: str, X: np.ndarray, cov_kind: str = "shrunk", given: np.ndarray | None = None) -> np.ndarray:
    """Weights from a window of weekly returns X (S x n, no NaN)."""
    S, n = X.shape
    if method == "given":
        g = np.clip(np.asarray(given, float), 0, None)
        return g / g.sum() if g.sum() > 0 else np.ones(n) / n
    if n == 1:
        return np.ones(1)
    cov = covariance(X, cov_kind)
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
    if method == "hrp":
        return hrp(cov)
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


def methods(given: np.ndarray | None = None) -> list[tuple[str, str]]:
    return METHODS + ([GIVEN] if given is not None and np.sum(given) > 0 else [])


def walk_forward(days: list[str], W: np.ndarray, window: int = 156, hold: int = 13, cov: str = "shrunk",
                 given: np.ndarray | None = None) -> dict:
    """Out-of-sample weekly returns of each method; at each rebalance only the assets with the whole window."""
    T, N = W.shape
    ms = methods(given)
    out = {m: np.full(T, np.nan) for m, _ in ms}
    history = {m: [] for m, _ in ms}
    turnover = {m: 0.0 for m, _ in ms}
    prev = {m: np.zeros(N) for m, _ in ms}
    shrink: list[float] = []
    first = None
    for t0 in range(window, T, hold):
        X = W[t0 - window:t0]
        cols = np.flatnonzero(np.isfinite(X).all(axis=0))
        if len(cols) == 0:
            continue
        if first is None:
            first = t0
        Xc = X[:, cols]
        if len(cols) > 1:
            shrink.append(shrunk_cov(Xc)[1])
        block = W[t0:t0 + hold]
        for m, _ in ms:
            w = np.zeros(N)
            w[cols] = weights(m, Xc, cov, None if given is None else np.asarray(given)[cols])
            turnover[m] += float(np.abs(w - prev[m]).sum())
            prev[m] = w
            history[m].append({"date": days[t0], "w": [round(float(v), 4) for v in w]})
            r = np.nan_to_num(block) @ w
            out[m][t0:t0 + hold] = r
    if first is None:
        return {"error": f"для распределения нужно больше {window} недель истории хотя бы у одного актива"}
    return {"first": days[first], "returns": out, "history": history, "methods": ms, "cov": cov,
            "shrinkage": float(np.mean(shrink)) if shrink else None,
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
