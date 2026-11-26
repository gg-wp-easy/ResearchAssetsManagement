"""Machine learning of the next month's returns across MOEX shares from the factor lab's factors, walk-forward.

- inputs: each factor's cross-sectional rank in the month, scaled to unit variance (a missing value is the middle, 0);
  target: the rank of the next month's total return the same way - the models learn the order, not the level, which
  outliers and market months do not move;
- walk-forward: the forecast for month k is made by models fitted on the months before k only (their returns ended by
  k's formation date, so nothing of the future leaks); refitted every REFIT months on all the months so far;
- the parameters are fixed in advance, none is tuned on the test months: the honest count of what was tried is the
  number of models times feature sets, which the deflated Sharpe ratio takes;
- models: the sum of the factors' ranks (no training: the a-priori composite), ridge regression, gradient-boosted
  trees, a small neural net; two feature sets - the price factors (from 2015) and everything with server-analytic-
  system's valuation (from 2022, when the reports start).

The forecasts are judged as factors (IC, quintiles, the top fifth against all after costs) on the months they cover.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import warnings

import numpy as np

from . import factors, sizing, universe
from .factors import rank_z
from .store import data_dir, single_thread_pool

VERSION = 1
REFIT = 3
SEED = 7
PRICE = ["mom", "rev", "lowvol", "lowbeta", "illiq"]
SETS = [
    ("price", "ценовые факторы", PRICE, 24),
    ("all", "все факторы и оценка SAS", PRICE + ["dy", "ep", "bp", "sp", "fcfp", "roe", "lowlev", "size", "sas_pe", "sas_all"], 12),
]
MODELS = [("sum", "сумма рангов (без обучения)"), ("ridge", "линейная регрессия"), ("gbm", "градиентный бустинг"),
          ("mlp", "нейросеть")]
BASELINES = [("mom", "моментум 12−1"), ("ep", "E/P")]


def design(m: factors.Month, keys: list[str]) -> np.ndarray:
    cols = []
    for k in keys:
        v = m.f.get(k, np.full(len(m.cols), np.nan))
        z = np.zeros(len(v))
        ok = np.isfinite(v)
        if ok.sum() > 2:
            z[ok] = rank_z(v[ok])
        cols.append(z)
    return np.column_stack(cols)


def eligible(m: factors.Month, keys: list[str]) -> bool:
    """A month enters a set when every factor of it is known for at least a third of the universe."""
    return all(k in m.f and np.isfinite(m.f[k]).mean() >= 1 / 3 for k in keys)


def make(model: str, seed: int):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.neural_network import MLPRegressor
    if model == "ridge":
        return Ridge(alpha=100.0)
    if model == "gbm":
        return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=200,
                                             l2_regularization=1.0, random_state=seed)
    if model == "mlp":
        return MLPRegressor(hidden_layer_sizes=(16,), activation="tanh", alpha=1.0, learning_rate_init=0.003,
                            max_iter=200, early_stopping=True, validation_fraction=0.15, n_iter_no_change=10,
                            random_state=seed)
    raise ValueError(model)


def run_one(job: tuple) -> dict:
    """Walk-forward forecasts of one model on one feature set: {month index: forecast list}, and the importance of the
    inputs at the last fit (the rise of the training error when one is shuffled)."""
    from threadpoolctl import threadpool_limits
    model, keys, min_train, data = job
    preds: dict[int, list[float]] = {}
    fitted, last = None, None
    with threadpool_limits(1), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for i, (idx, X, y) in enumerate(data):
            if model == "sum":
                preds[idx] = X.mean(axis=1).tolist()
                continue
            if i < min_train:
                continue
            if fitted is None or (i - min_train) % REFIT == 0:
                Xtr = np.vstack([d[1][np.isfinite(d[2])] for d in data[:i]])
                ytr = np.concatenate([d[2][np.isfinite(d[2])] for d in data[:i]])
                fitted = make(model, SEED).fit(Xtr, ytr)
                last = (Xtr, ytr)
            preds[idx] = fitted.predict(X).tolist()
        importance = {}
        if fitted is not None and last is not None:
            Xtr, ytr = last
            rng = np.random.default_rng(SEED)
            pick = rng.choice(len(ytr), min(4000, len(ytr)), replace=False)
            Xs, ys = Xtr[pick], ytr[pick]
            base = float(np.mean((fitted.predict(Xs) - ys) ** 2))
            for c, k in enumerate(keys):
                Xp = Xs.copy()
                Xp[:, c] = rng.permutation(Xp[:, c])
                importance[k] = max(float(np.mean((fitted.predict(Xp) - ys) ** 2)) - base, 0.0)
            total = sum(importance.values()) or 1.0
            importance = {k: v / total for k, v in importance.items()}
        elif model == "sum":
            importance = {k: 1 / len(keys) for k in keys}
    return {"preds": preds, "importance": importance}


def _cache_path(start: str, top: int, p: universe.Panel, months: list[factors.Month]) -> object:
    key = hashlib.sha1(json.dumps([VERSION, REFIT, start, top, p.dates[-1], len(months)]).encode()).hexdigest()[:12]
    return data_dir() / f"ml-v{VERSION}-{key}.json"


def forecasts(p: universe.Panel, months: list[factors.Month], start: str, top: int, progress=None) -> dict:
    """{set: {model: {"preds": {month index: list}, "importance": {}}}}, from the disk cache when the panel and the
    months are the same."""
    path = _cache_path(start, top, p, months)
    if path.exists():
        try:
            blob = json.loads(path.read_text())
            return {s: {m: {"preds": {int(k): v for k, v in r["preds"].items()}, "importance": r["importance"]}
                        for m, r in ms.items()} for s, ms in blob.items()}
        except (ValueError, KeyError):
            pass
    jobs, names = [], []
    for skey, _, keys, min_train in SETS:
        data = [(i, design(m, keys), rank_target(m)) for i, m in enumerate(months) if eligible(m, keys)]
        for mkey, _ in MODELS:
            jobs.append((mkey, keys, min_train, data))
            names.append((skey, mkey))
    out: dict = {}
    workers = max(1, min(len(jobs), (os.cpu_count() or 2) - 1, 8))
    with single_thread_pool(workers) as pool:
        for (skey, mkey), res in zip(names, pool.map(run_one, jobs)):
            out.setdefault(skey, {})[mkey] = res
            if progress:
                progress(f"{skey}/{mkey}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def rank_target(m: factors.Month) -> np.ndarray:
    y = np.full(len(m.fwd), np.nan)
    ok = np.isfinite(m.fwd)
    if ok.sum() > 2:
        y[ok] = rank_z(m.fwd[ok])
    return y


def lab(start: str = "2015-01-01", top: int = 100, cost: float = 0.002) -> dict:
    t0 = time.time()
    p = universe.panel()
    months, warns = factors.build_months(p, start, top)
    if not months:
        raise ValueError("нет ни одного месяца с данными")
    fc = forecasts(p, months, start, top)
    rows, trial_srs, nets = [], [], {}
    for skey, stitle, keys, _ in SETS:
        trained = sorted(set.intersection(*[set(r["preds"]) for k, r in fc.get(skey, {}).items() if k != "sum"])) \
            if fc.get(skey) else []
        span = set(trained)  # every model of a set is judged on the same months: those all of them forecast
        for mkey, mtitle in MODELS:
            res = fc.get(skey, {}).get(mkey)
            if not res:
                continue
            key = f"ml_{skey}_{mkey}"
            for i in span:
                months[i].f[key] = np.array(res["preds"][i])
            ev = factors.evaluate([m for i, m in enumerate(months) if i in span], p.dates, p.tickers, key, cost,
                                  title=f"{mtitle}")
            if ev is None:
                continue
            ev.update({"set": skey, "set_title": stitle, "model": mkey, "importance": res["importance"],
                       "inputs": keys, "data": "price",
                       "desc": f"прогноз: {mtitle.split(' (')[0]}, признаки — {stitle}"})
            rows.append(ev)
            nets[key] = ev["series"]["net"]
        for bkey, btitle in BASELINES:
            if bkey not in keys:
                continue
            ev = factors.evaluate([m for i, m in enumerate(months) if i in span], p.dates, p.tickers, bkey, cost,
                                  title=f"{btitle} (один фактор)")
            if ev:
                ev.update({"set": skey, "set_title": stitle, "model": "factor", "importance": {}, "inputs": [bkey],
                           "data": "price", "desc": f"{btitle} без модели, на тех же месяцах — для сравнения"})
                rows.append(ev)
                nets[f"{skey}_{bkey}"] = ev["series"]["net"]
    # the trials: every ML row and baseline here plus every factor of the lab (what was looked at before choosing)
    lab_rows = [r for r in (factors.evaluate(months, p.dates, p.tickers, k, cost) for k, *_ in factors.FACTORS) if r]
    for r in lab_rows:
        trial_srs.append(_sr(r["series"]["net"]))
    trial_srs += [_sr(v) for v in nets.values()]
    for r in rows:
        r["dsr"] = sizing.deflated_sharpe(np.array(r["series"]["net"], float), len(trial_srs))
    return {"meta": {"start": start, "top": top, "cost": cost, "refit": REFIT, "trials": len(trial_srs),
                     "warnings": warns, "panel_to": p.dates[-1]},
            "sets": [{"key": s, "title": t, "inputs": [factors.TITLE[k] for k in ks], "min_train": mt} for s, t, ks, mt in SETS],
            "models": [{"key": k, "title": t} for k, t in MODELS], "rows": rows,
            "titles": {k: factors.TITLE[k] for _, _, ks, _ in SETS for k in ks}, "elapsed": time.time() - t0}


def _sr(x) -> float:
    a = np.array([v for v in x if v is not None and math.isfinite(v)], float)
    return float(a.mean() / a.std(ddof=1)) if len(a) > 2 and a.std() > 0 else math.nan
