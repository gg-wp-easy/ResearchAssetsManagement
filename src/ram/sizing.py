"""Kelly's criterion with the error of the estimate, and how much a Sharpe ratio can be trusted.

  g(f) = mu f - sigma^2 f^2 / 2,  f* = mu / sigma^2,  g* = SR^2 / 2,  g(c f*) / g* = 2c - c^2
  E g(c f_hat) = SR^2 (c - c^2/2) - c^2 / (2T)  ->  c* = T SR^2 / (T SR^2 + 1)
  SE(SR_hat) ~ sqrt((1 + SR^2/2) / T),   SE(SR_1 - SR_2) ~ sqrt(2 (1 - rho) / T),   T(t = 2) = 8 (1 - rho) / dSR^2
  E[max of K Sharpes with no skill] ~ SE * ((1 - g) Phi^-1(1 - 1/K) + g Phi^-1(1 - 1/(K e))),  g = 0.5772
  (Lo 2002; Memmel 2003; Bailey and Lopez de Prado 2014).
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats as sst

EULER = 0.5772156649


def kelly(x: np.ndarray, ppy: float) -> dict:
    mu = float(x.mean() * ppy)
    var = float(x.var() * ppy)
    if var <= 0:
        return {}
    sr = mu / math.sqrt(var)
    T = len(x) / ppy
    f = mu / var  # leverage on the book as it is
    c_now = 1 / f if f > 0 else math.inf
    c_star = T * sr * sr / (T * sr * sr + 1) if sr > 0 else 0.0
    curve = [[round(c, 3), round(2 * c - c * c, 4)] for c in np.linspace(0, 2.2, 89)]
    return {"mu": mu, "vol": math.sqrt(var), "sharpe": sr, "years": T, "f_star": f, "c_now": c_now,
            "growth_now": 2 * c_now - c_now ** 2 if math.isfinite(c_now) else None,
            "kelly_vol": f * math.sqrt(var) if f > 0 else 0.0, "c_star": c_star, "curve": curve,
            "g_star": sr * sr / 2}


def sharpe_se(sr: float, years: float) -> float:
    return math.sqrt((1 + sr * sr / 2) / max(years, 1e-9))


def expected_max_sharpe(k: int, se: float) -> float:
    if k <= 1:
        return 0.0
    return se * ((1 - EULER) * sst.norm.ppf(1 - 1 / k) + EULER * sst.norm.ppf(1 - 1 / (k * math.e)))


def deflated_sharpe(x: np.ndarray, trials: int) -> dict:
    """Bailey and Lopez de Prado's deflated Sharpe ratio of the period returns x after `trials` strategies were tried:
    the probability that the true Sharpe ratio is above the best one of `trials` strategies without skill would show
    over the same T periods,
        DSR = Phi((SR - SR0) sqrt(T - 1) / sqrt(1 - skew SR + (kurt - 1) / 4 SR^2)),
        SR0 = sqrt(1 / T) ((1 - g) Phi^-1(1 - 1/K) + g Phi^-1(1 - 1/(K e))).
    SR0 takes the variance of a no-skill Sharpe estimate (1/T), not the spread of the tried Sharpe ratios: the trials
    here are different factors, not variations of one, and their spread would mostly be real differences.
    Per-period Sharpe ratios; kurt is the raw kurtosis (3 for the normal); PSR is the same against zero."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 12 or x.std() == 0:
        return {}
    T = len(x)
    sr = float(x.mean() / x.std(ddof=1))
    k = max(int(trials), 1)
    sr0 = math.sqrt(1 / T) * ((1 - EULER) * sst.norm.ppf(1 - 1 / k) + EULER * sst.norm.ppf(1 - 1 / (k * math.e))) \
        if k > 1 else 0.0
    skew, kurt = float(sst.skew(x)), float(sst.kurtosis(x, fisher=False))
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    return {"sr": sr, "sr0": sr0, "trials": k, "months": T,
            "dsr": float(sst.norm.cdf((sr - sr0) * math.sqrt(T - 1) / denom)),
            "psr": float(sst.norm.cdf(sr * math.sqrt(T - 1) / denom))}


def compare(a: np.ndarray, b: np.ndarray, ppy: float) -> dict:
    """Two daily return series on the same days: their correlation, the Sharpe difference, its t and the years a t of 2
    would need."""
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 60 or a.std() == 0 or b.std() == 0:
        return {}
    rho = float(np.corrcoef(a, b)[0, 1])
    s1 = a.mean() / a.std() * math.sqrt(ppy)
    s2 = b.mean() / b.std() * math.sqrt(ppy)
    T = len(a) / ppy
    d = float(s1 - s2)
    se = math.sqrt(max(2 * (1 - rho), 1e-12) / T)
    return {"rho": rho, "sr_a": float(s1), "sr_b": float(s2), "diff": d, "se": se, "t": d / se,
            "years_needed": 8 * (1 - rho) / (d * d) if abs(d) > 1e-9 else None}


def significance(x: np.ndarray, ppy: float) -> dict:
    T = len(x) / ppy
    sr = float(x.mean() / x.std() * math.sqrt(ppy)) if x.std() > 0 else 0.0
    se = sharpe_se(sr, T)
    luck = []
    for years in (3, 5, 10, round(T, 1)):
        se0 = sharpe_se(0.0, years)
        luck.append({"years": years, "values": [{"k": k, "sr": expected_max_sharpe(k, se0)} for k in (5, 10, 20, 50, 100)]})
    need = [{"dsr": d, "rho": r, "years": 8 * (1 - r) / (d * d)} for d in (0.2, 0.5) for r in (0.0, 0.5, 0.9)]
    return {"sharpe": sr, "years": T, "se": se, "low": sr - 2 * se, "high": sr + 2 * se, "t": sr / se if se else 0.0,
            "luck": luck, "need": need}
