"""Regimes: a two-state Gaussian hidden Markov model (Hamilton 1989), fitted by EM (Baum-Welch with the Hamilton
filter and the Kim smoother).

  P(s_t = j | s_{t-1} = i) = p_ij,   r_t | s_t = k ~ N(mu_k, sigma_k^2)
  filter:   xi_{t|t} = xi_{t|t-1} * eta_t / 1'(xi_{t|t-1} * eta_t),   xi_{t+1|t} = P' xi_{t|t}
  expected length of regime k: 1 / (1 - p_kk)

State 1 is the one with the larger volatility ("bad times"). With a few crises in the data the bad state rests on a
handful of points: use it as a risk multiplier (volatility and correlation), not as a signal of direction.
"""
from __future__ import annotations

import math

import numpy as np


def _pdf(y: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * ((y[:, None] - mu[None, :]) / sd[None, :]) ** 2) / (sd[None, :] * math.sqrt(2 * math.pi))


def fit_hmm2(y: np.ndarray, iters: int = 300, tol: float = 1e-7) -> dict:
    y = np.asarray(y, float)
    T = len(y)
    s = y.std()
    mu = np.array([y.mean(), y.mean()])
    sd = np.array([0.7 * s, 1.6 * s])
    P = np.array([[0.97, 0.03], [0.10, 0.90]])
    pi = np.array([0.8, 0.2])
    last = -np.inf
    for _ in range(iters):
        eta = _pdf(y, mu, sd) + 1e-300
        filt = np.zeros((T, 2))
        pred = np.zeros((T, 2))
        ll = 0.0
        p = pi
        for t in range(T):
            pred[t] = p
            f = p * eta[t]
            c = f.sum()
            ll += math.log(c)
            filt[t] = f / c
            p = P.T @ filt[t]
        smooth = np.zeros((T, 2))
        smooth[-1] = filt[-1]
        joint = np.zeros((2, 2))
        for t in range(T - 2, -1, -1):
            ratio = smooth[t + 1] / np.maximum(pred[t + 1], 1e-300)
            smooth[t] = filt[t] * (P @ ratio)
            joint += filt[t][:, None] * P * ratio[None, :]
        occ = smooth[:-1].sum(axis=0)
        P = joint / np.maximum(occ[:, None], 1e-12)
        P = P / P.sum(axis=1, keepdims=True)
        w = smooth.sum(axis=0)
        mu = (smooth * y[:, None]).sum(axis=0) / w
        sd = np.sqrt((smooth * (y[:, None] - mu[None, :]) ** 2).sum(axis=0) / w)
        sd = np.maximum(sd, 0.05 * s)
        pi = smooth[0]
        if ll - last < tol * abs(ll):
            break
        last = ll
    if sd[0] > sd[1]:  # state 1 = the volatile one
        mu, sd, P = mu[::-1], sd[::-1], P[::-1, ::-1]
        filt, smooth = filt[:, ::-1], smooth[:, ::-1]
    return {"mu": mu, "sd": sd, "P": P, "filtered": filt, "smoothed": smooth, "loglik": ll}


def regimes(days: list[str], W: np.ndarray, book_weekly: np.ndarray, labels: list[str], per_year: float = 52) -> dict:
    """Fit the HMM to the basket's equal-risk weekly return (each asset scaled to its own volatility, averaged), then
    describe the assets and the book in each regime."""
    vol = np.nanstd(W, axis=0)
    vol = np.where(vol > 0, vol, np.nan)
    scaled = W / vol[None, :]
    with np.errstate(invalid="ignore"):
        mkt = np.nanmean(scaled, axis=1)
    keep = np.isfinite(mkt)
    if keep.sum() < 150:
        return {"error": "для режимов нужно хотя бы 150 недель общей истории"}
    y = mkt[keep]
    fit = fit_hmm2(y)
    sm = fit["smoothed"]
    Wk, bk = W[keep], book_weekly[keep]
    states = []
    for k in range(2):
        p = sm[:, k]
        wsum = p.sum()
        assets = []
        for j in range(W.shape[1]):
            col = Wk[:, j]
            ok = np.isfinite(col)
            pw = p[ok]
            if pw.sum() < 5:
                assets.append({"mean": None, "vol": None})
                continue
            m = float((pw * col[ok]).sum() / pw.sum())
            v = float(math.sqrt((pw * (col[ok] - m) ** 2).sum() / pw.sum()))
            assets.append({"mean": m * per_year, "vol": v * math.sqrt(per_year)})
        bm = float((p * bk).sum() / wsum)
        bv = float(math.sqrt((p * (bk - bm) ** 2).sum() / wsum))
        corr = _weighted_mean_corr(Wk, p)
        states.append({"share": float(wsum / len(p)), "duration_weeks": float(1 / max(1 - fit["P"][k, k], 1e-9)),
                       "mkt_vol": float(fit["sd"][k] * math.sqrt(per_year)), "assets": assets,
                       "book_mean": bm * per_year, "book_vol": bv * math.sqrt(per_year),
                       "book_sharpe": bm / bv * math.sqrt(per_year) if bv > 0 else 0.0, "avg_corr": corr})
    kept_days = [d for d, k in zip(days, keep) if k]
    return {"dates": kept_days, "p_bad": [round(float(v), 4) for v in fit["filtered"][:, 1]],
            "p_bad_smooth": [round(float(v), 4) for v in sm[:, 1]], "states": states,
            "transition": fit["P"].round(4).tolist(), "now": float(fit["filtered"][-1, 1]), "labels": labels}


def _weighted_mean_corr(W: np.ndarray, p: np.ndarray) -> float | None:
    N = W.shape[1]
    if N < 2:
        return None
    vals = []
    for a in range(N):
        for b in range(a + 1, N):
            ok = np.isfinite(W[:, a]) & np.isfinite(W[:, b])
            if ok.sum() < 20:
                continue
            w = p[ok]
            x, y = W[ok, a], W[ok, b]
            mx, my = (w * x).sum() / w.sum(), (w * y).sum() / w.sum()
            cov = (w * (x - mx) * (y - my)).sum()
            sx, sy = math.sqrt((w * (x - mx) ** 2).sum()), math.sqrt((w * (y - my) ** 2).sum())
            if sx > 0 and sy > 0:
                vals.append(cov / (sx * sy))
    return float(np.mean(vals)) if vals else None
