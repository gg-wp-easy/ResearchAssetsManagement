"""The bond sleeve's mix by the Bank of Russia's policy: a regime from the key rate known at each month's end, a mix of
kinds set in advance for each regime (the prior), and a walk-forward optimum - each month the mean-variance best mix of
the kinds on the past months of the same regime only, halfway back to the prior. No month's choice sees its future.

Regimes over the last POLICY_WEEKS weeks:
* tight - the rate was raised and not cut since;
* ease  - the rate was cut and not raised since;
* hold  - it did not change (or no key rate yet: before 2013-09-13).
"""
from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
from scipy.optimize import minimize

REGIMES = [("tight", "ужесточение"), ("hold", "пауза"), ("ease", "смягчение")]
REGIME_TITLES = dict(REGIMES)
POLICY_WEEKS = 26
CANDIDATES = ["corp_float", "ofz_float", "ofz_short", "corp_fixed", "ofz_ladder"]
BASE = {"corp_float": 0.5, "ofz_short": 0.25, "corp_fixed": 0.25}  # the user's choice: corporate floaters and short bonds
PRIOR = {  # set before any test, from what each regime does to the kinds
    "tight": {"corp_float": 0.6, "ofz_short": 0.2, "corp_fixed": 0.2},  # rates rise: floating coupons, short fixed ones
    "hold": {"corp_float": 0.4, "ofz_short": 0.3, "corp_fixed": 0.3},  # a pause at a high rate: lock the yield for a while
    "ease": {"corp_float": 0.2, "ofz_short": 0.2, "corp_fixed": 0.3, "ofz_ladder": 0.3},  # cuts: duration earns
}
MIN_MONTHS = 12  # months of a regime before its own optimum is used
SHRINK_MONTHS = 12  # the regime's mean shrinks to the all-months mean as if this many months of it
RISK_AVERSION = 10.0  # on monthly returns
CAP = 0.6  # the most of one kind
TO_PRIOR = 0.5  # the optimum's weight; the rest is the prior's
SWITCH_COST = 0.0015  # a share of the sleeve moved between kinds, one way (half the spread and the fee)


def regimes(days: list[str], key: np.ndarray) -> list[str]:
    """The regime of every week from the key rate on the weeks (NaN before it existed)."""
    out = []
    for t in range(len(days)):
        lo = max(0, t - POLICY_WEEKS)
        k = key[lo:t + 1]
        k = k[np.isfinite(k)]
        moves = np.diff(k)
        moves = moves[np.abs(moves) >= 0.0025 - 1e-9]
        out.append("hold" if not len(moves) else "tight" if moves[-1] > 0 else "ease")
    return out


def monthly(r: np.ndarray, ends: list[int]) -> np.ndarray:
    """Return over each month (between consecutive month-end weeks); NaN when the series had not started."""
    out = np.full(len(ends) - 1, np.nan)
    for i, (a, b) in enumerate(pairwise(ends)):
        x = r[a + 1:b + 1]
        if np.isfinite(x).all() and len(x):
            out[i] = float(np.prod(1 + x) - 1)
    return out


def optimum(mu: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """max mu'w - RISK_AVERSION/2 w'Cw, w >= 0, sum 1, w <= CAP."""
    n = len(mu)
    cap = max(CAP, 1.0 / n)
    res = minimize(lambda w: -(mu @ w) + RISK_AVERSION / 2 * w @ cov @ w, np.full(n, 1.0 / n), method="SLSQP",
                   bounds=[(0.0, cap)] * n, constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}])
    w = np.clip(res.x if res.success else np.full(n, 1.0 / n), 0, None)
    return w / w.sum()


def _prior(regime: str, alive: list[str]) -> dict[str, float]:
    p = {k: v for k, v in PRIOR[regime].items() if k in alive}
    if not p:  # none of the regime's kinds exists yet: the alive candidates equally
        return {k: 1.0 / len(alive) for k in alive}
    s = sum(p.values())
    return {k: v / s for k, v in p.items()}


def walk_forward(series: dict[str, np.ndarray], ends: list[int], regime: list[str]) -> tuple[dict[int, dict], dict[int, dict]]:
    """({month-end week: prior mix}, {month-end week: optimised mix}) - the optimum of month i uses months before i."""
    M = {k: monthly(series[k], ends) for k in CANDIDATES if k in series}
    rules: dict[int, dict] = {}
    opts: dict[int, dict] = {}
    for i, t in enumerate(ends):
        g = regime[t]
        alive = [k for k in M if np.isfinite(series[k][max(0, t - 3):t + 1]).all()]  # the kind trades at t
        if not alive:
            continue
        prior = _prior(g, alive)
        rules[t] = prior
        past = np.column_stack([M[k][:i] for k in alive]) if i else np.zeros((0, len(alive)))
        ok = np.isfinite(past).all(axis=1)
        same = ok & np.array([regime[ends[j]] == g for j in range(i)], bool)
        if same.sum() < MIN_MONTHS or ok.sum() < 2 * len(alive):
            opts[t] = prior
            continue
        mu_all, mu_g = past[ok].mean(axis=0), past[same].mean(axis=0)
        n = same.sum()
        mu = (n * mu_g + SHRINK_MONTHS * mu_all) / (n + SHRINK_MONTHS)
        cov = np.cov(past[ok].T) if len(alive) > 1 else np.atleast_2d(past[ok].var())
        cov = 0.5 * cov + 0.5 * np.diag(np.diag(cov))  # half way to the diagonal: few months, five kinds
        w = optimum(mu, cov)
        mix = {k: TO_PRIOR * prior.get(k, 0.0) + (1 - TO_PRIOR) * float(x) for k, x in zip(alive, w)}
        opts[t] = {k: v for k, v in mix.items() if v > 1e-4}
    return rules, opts


def dynamic_blend(series: dict[str, np.ndarray], mixes: dict[int, dict], T: int, cost: float = SWITCH_COST) -> np.ndarray:
    """Weekly return of the sleeve holding each month the mix chosen at its start; the share moved between kinds pays
    `cost`."""
    out = np.full(T, np.nan)
    weeks = sorted(mixes)
    prev: dict[str, float] = {}
    for a, b in zip(weeks, weeks[1:] + [T - 1]):
        mix = mixes[a]
        R = np.column_stack([np.nan_to_num(series[k][a + 1:b + 1]) for k in mix]) if mix else np.zeros((b - a, 0))
        w = np.array(list(mix.values()))
        seg = R @ w if len(w) else np.zeros(b - a)
        moved = sum(abs(mix.get(k, 0.0) - prev.get(k, 0.0)) for k in set(mix) | set(prev)) / 2
        if len(seg) and prev:
            seg[0] -= cost * 2 * moved  # sold and bought
        out[a + 1:b + 1] = seg
        prev = mix
    return out


def describe(regime: list[str], days: list[str], key: np.ndarray, rules: dict[int, dict], opts: dict[int, dict]) -> dict:
    """Today's regime, its start, the key rate and both mixes; the regimes month by month."""
    t = max(opts) if opts else len(days) - 1
    g = regime[t]
    since = t
    while since > 0 and regime[since - 1] == g:
        since -= 1
    history = [{"date": days[w], "regime": regime[w], "key": None if not math.isfinite(key[w]) else float(key[w]),
                "mix": opts.get(w, {})} for w in sorted(opts)]
    return {"regime": g, "title": REGIME_TITLES[g], "since": days[since], "date": days[t],
            "key": None if not math.isfinite(key[t]) else float(key[t]), "rule": rules.get(t, {}), "mix": opts.get(t, {}),
            "priors": PRIOR, "base": BASE, "history": history,
            "params": {"weeks": POLICY_WEEKS, "min_months": MIN_MONTHS, "shrink_months": SHRINK_MONTHS,
                       "risk_aversion": RISK_AVERSION, "cap": CAP, "to_prior": TO_PRIOR, "switch_cost": SWITCH_COST}}
