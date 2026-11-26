"""server-analytic-system's fair-multiple valuation (its analysis/analysis_stocks/valuation and
docs/algorithms/stocks/valuation) re-run point in time at every month-end, so that "undervalued" can be tested on
some 55 dates instead of the one snapshot of 31.10.2025.

For each multiple m (P/E, P/BV, P/S, P/FCF) and date:

    ln m^ = ln b_s + f(x),    gap = ln m^ - ln m = ln(fair price / price)

- companies: TQBR shares traded on the day with a median daily value of at least 1 mln rubles over 13 weeks (the
  original's liquidity rule), one row per company (its ordinary and preferred share share it), the last annual
  report published before the day, the multiple inside its range (P/E 1-100 ...);
- b_s: the median of the company's sector shrunk to the market's median (empirical Bayes, K = sigma^2 / tau^2 of a
  one-way ANOVA);
- x: the candidates of the multiple's formula (Damodaran) known for 60% of the companies, clipped at the 2nd and 98th
  percentiles and imputed by the median of the training rows; forward inclusion while every VIF <= 5, every HC3
  p <= 0.05 and the leave-one-out RMSE falls (one stays if none beats the sector base);
- f: OLS on the standardized indicators; a CART tree (depth 2-4, leaf 4/6/8, alpha 0/0.01/0.03 by 4-fold CV); a tanh
  MLP (4 or 8 units, alpha 0.3/1/3 by 3-fold CV, the mean of 5 nets); clusters: k-means of ln m and the companion
  variable, a group's distance below the market line times sd(ln m);
- every company valued by models fitted without it (5 folds by company); the hybrid is the mean of the four ln m^.

Differences from the original: the share list is the board's on the date (not today's T-Invest list; no qualified-
investor filter), one cross-fit repeat instead of three, the share counts of the annual report, no "undervalued needs
a profit" class rule (the gap itself is the factor).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import warnings

import numpy as np
from scipy import stats

from . import sas, universe
from .store import data_dir, single_thread_pool

VERSION = 1
SEED = 42
MIN_VALUE = 1e6  # rubles a day, median over 13 weeks
MIN_COMPANIES = 25
COVERAGE, VIF_LIMIT, ALPHA, SHRINKAGE = 0.6, 5.0, 0.05, 3.0
QUANTILES = (0.02, 0.98)

MULTIPLES = {
    "pe": {"label": "P/E", "denominator": "ni", "lo": 1.0, "hi": 100.0, "companion": "g", "range": (-5.0, 30.0), "sign": 1},
    "pb": {"label": "P/BV", "denominator": "book", "lo": 0.1, "hi": 30.0, "companion": "roe", "range": (-20.0, 60.0), "sign": 1},
    "ps": {"label": "P/S", "denominator": "rev", "lo": 0.05, "hi": 30.0, "companion": "npm", "range": (-20.0, 50.0), "sign": 1},
    "pfcf": {"label": "P/FCF", "denominator": "fcf", "lo": 1.0, "hi": 100.0, "companion": "fcf_margin", "range": (0.0, 50.0),
             "sign": -1},
}
COMMON = ["g", "revenue_cagr_3y", "revenue_growth_1y", "payout_ratio", "dividend_consistency", "beta",
          "log_debt_to_equity", "net_debt_ebitda", "interest_coverage", "margin_volatility", "profit_years_share",
          "log_revenue"]
CANDIDATES = {
    "pe": ["roe", "roa", "npm", "ebitda_margin", "profit_growth_1y", "cash_conversion", "cash_assets"] + COMMON,
    "pb": ["roe", "roa", "roce", "equity_assets"] + COMMON,
    "ps": ["npm", "operating_margin", "ebitda_margin", "fcf_margin", "asset_turnover"] + COMMON,
    "pfcf": ["fcf_margin", "npm", "roce", "capex_revenue", "capex_amortization", "cash_assets"] + COMMON,
}
ANALYSES = [("reg", "регрессия"), ("cl", "кластеры"), ("tree", "дерево"), ("nn", "нейросеть")]


# ---------------------------------------------------------------------------- the companies of a date


def _ratio(a: float, b: float, scale: float = 1.0, positive: bool = True) -> float:
    if not (math.isfinite(a) and math.isfinite(b)) or b == 0 or (positive and b < 0):
        return math.nan
    return a / b * scale


def report_features(rep: sas.Report, earlier: dict[str, sas.Report]) -> dict[str, float]:
    """The price-free indicators of one annual report (`earlier`: the same standard's reports by year)."""
    g = rep.get
    ni, book = g("net_income"), g("net_assets", "book_value", "capital")
    rev, assets, ebitda = g("revenue"), g("assets"), g("ebitda")
    ebit, ocf, fcf, capex = g("operating_income"), g("ocf"), g("fcf"), g("capex")
    debt, nd, cash = g("debt"), g("net_debt"), g("cash")
    if not math.isfinite(nd) and math.isfinite(debt):
        nd = debt - (cash if math.isfinite(cash) else 0.0)
    roe = _ratio(ni, book, 100.0)
    payout = g("div_payout_ratio")
    year = int(rep.period)

    def past(k: int, field: str) -> float:
        r = earlier.get(str(year - k))
        return r.get(field) if r else math.nan

    margins, profits = [], []
    for y in range(year - 9, year + 1):
        r = earlier.get(str(y)) if y != year else rep
        if r is None:
            continue
        n_, r_ = r.get("net_income"), r.get("revenue")
        if math.isfinite(n_):
            profits.append(n_ > 0)
            if r_ > 0:
                margins.append(n_ / r_ * 100)
    rev1, rev3, ni1 = past(1, "revenue"), past(3, "revenue"), past(1, "net_income")
    capital = book + nd if math.isfinite(book) and math.isfinite(nd) else math.nan
    return {
        "ni": ni, "book": book, "rev": rev, "fcf": fcf,
        "roe": roe, "roa": _ratio(ni, assets, 100.0), "npm": _ratio(ni, rev, 100.0),
        "ebitda_margin": _ratio(ebitda, rev, 100.0), "operating_margin": _ratio(ebit, rev, 100.0),
        "fcf_margin": _ratio(fcf, rev, 100.0), "cash_conversion": _ratio(ocf, ni),
        "cash_assets": _ratio(cash, assets, 100.0), "equity_assets": _ratio(book, assets, 100.0),
        "asset_turnover": _ratio(rev, assets), "roce": _ratio(ebit, capital, 100.0),
        "capex_revenue": _ratio(capex, rev, 100.0), "capex_amortization": _ratio(capex, g("amortization")),
        "payout_ratio": payout,
        "g": (1 - payout / 100) * roe if math.isfinite(payout) and math.isfinite(roe) else math.nan,
        "revenue_growth_1y": (rev / rev1 - 1) * 100 if rev > 0 and rev1 > 0 else math.nan,
        "revenue_cagr_3y": ((rev / rev3) ** (1 / 3) - 1) * 100 if rev > 0 and rev3 > 0 else math.nan,
        "profit_growth_1y": (ni / ni1 - 1) * 100 if ni > 0 and ni1 > 0 else math.nan,
        "margin_volatility": float(np.std(margins)) if len(margins) >= 3 else math.nan,
        "profit_years_share": float(np.mean(profits)) if len(profits) >= 3 else math.nan,
        "log_debt_to_equity": math.log1p(debt / book) if book > 0 and debt >= 0 else math.nan,
        "net_debt_ebitda": _ratio(nd, ebitda), "interest_coverage": _ratio(ebitda, g("interest_expenses")),
        "log_revenue": math.log(rev) if rev > 0 else math.nan,
    }


def companies(p: universe.Panel, t: int, M: np.ndarray, reps: dict, sector_of: dict[str, str]) -> list[dict]:
    """The rows of week t: one per company with a report, its tickers, sector, market cap and indicators."""
    from .factors import class_tickers, company_cap
    day = p.dates[t]
    col = {tk: j for j, tk in enumerate(p.tickers)}
    present = np.isfinite(p.P)
    lo = max(0, t - 12)
    med = np.median(np.where(present[lo:t + 1], p.V[lo:t + 1], 0.0), axis=0)
    ok = (p.V[t] > 0) & present[t] & (med >= MIN_VALUE)
    traded = {p.tickers[j] for j in np.flatnonzero(present[t])}
    divs = sas.dividends() or {}
    covered = sas.covered()
    year = int(day[:4])
    by_company: dict[str, dict] = {}
    for j in np.flatnonzero(ok):
        ticker = p.tickers[j]
        rep = sas.report_as_of(reps.get(ticker, []), day)
        if rep is None:
            continue
        ordinary, _ = class_tickers(rep.page or ticker, traded)
        row = by_company.get(ordinary)
        if row is not None:
            row["tickers"].append(ticker)
            continue
        cap = company_cap(p, t, rep, ticker, col, traded)
        if not cap > 0:
            continue
        earlier = {r.period: r for r in reps.get(ticker, []) if r.standard == rep.standard and r.published < day}
        feats = report_features(rep, earlier)
        main = ordinary if ordinary in col and present[t, col[ordinary]] else ticker
        w, m = p.R[max(0, t - 103):t + 1, col[main]], M[max(0, t - 103):t + 1]
        both = np.isfinite(w) & np.isfinite(m)
        feats["beta"] = float(np.cov(w[both], m[both])[0, 1] / m[both].var(ddof=1)) if both.sum() >= 52 else math.nan
        if main in covered or ticker in covered:
            paid = {d.record[:4] for d in divs.get(main, []) + divs.get(ticker, []) if d.record < day}
            feats["dividend_consistency"] = sum(str(y) in paid for y in (year - 1, year - 2, year - 3)) / 3
        else:
            feats["dividend_consistency"] = math.nan
        sector = sector_of.get(ordinary) or sector_of.get(ticker) or "other"
        by_company[ordinary] = {"company": ordinary, "tickers": [ticker], "sector": sector, "cap": cap,
                                "report": f"{rep.standard} {rep.period}", **feats}
    return list(by_company.values())


# ---------------------------------------------------------------------------- the analyses of one multiple


class Pre:
    """Quantile clipping and median imputation learned from training rows."""

    def fit(self, X: np.ndarray) -> "Pre":
        self.lo, self.hi, self.med = [], [], []
        for c in range(X.shape[1]):
            v = X[np.isfinite(X[:, c]), c]
            lo, hi = (np.quantile(v, QUANTILES) if len(v) else (np.nan, np.nan))
            self.lo.append(lo)
            self.hi.append(hi)
            self.med.append(float(np.median(np.clip(v, lo, hi))) if len(v) else 0.0)
        return self

    def __call__(self, X: np.ndarray) -> np.ndarray:
        out = X.copy()
        for c in range(X.shape[1]):
            if np.isfinite(self.lo[c]):
                out[:, c] = np.clip(out[:, c], self.lo[c], self.hi[c])
            out[~np.isfinite(out[:, c]), c] = self.med[c]
        return out


class SectorBase:
    def fit(self, sectors: np.ndarray, y: np.ndarray) -> "SectorBase":
        groups = sorted(set(sectors))
        n, k = len(y), len(groups)
        means = {s: y[sectors == s].mean() for s in groups}
        counts = {s: int((sectors == s).sum()) for s in groups}
        if k < 2 or n <= k:
            K = SHRINKAGE
        else:
            within = sum(((y[sectors == s] - means[s]) ** 2).sum() for s in groups) / (n - k)
            between = sum(counts[s] * (means[s] - y.mean()) ** 2 for s in groups) / (k - 1)
            n0 = (n - sum(c * c for c in counts.values()) / n) / (k - 1)
            tau2 = (between - within) / n0
            K = within / tau2 if tau2 > 1e-9 else 1e6
        self.overall = float(np.median(y))
        self.values = {s: (counts[s] * float(np.median(y[sectors == s])) + K * self.overall) / (counts[s] + K)
                       for s in groups}
        return self

    def __call__(self, sectors: np.ndarray) -> np.ndarray:
        return np.array([self.values.get(s, self.overall) for s in sectors])


def strict_fit(y: np.ndarray, Z: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """(HC3 p-values of the slopes, VIF, leave-one-out RMSE) of OLS of y on Z with an intercept."""
    n, k = Z.shape
    X = np.column_stack([np.ones(n), Z])
    inv = np.linalg.pinv(X.T @ X)
    beta = inv @ X.T @ y
    e = y - X @ beta
    h = np.einsum("ij,jk,ik->i", X, inv, X)
    scaled = e / np.clip(1 - h, 1e-6, None)
    cov = inv @ (X.T * scaled ** 2) @ X @ inv
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        tt = np.where(se > 0, beta / se, 0.0)
    pv = 2 * stats.t.sf(np.abs(tt), max(n - k - 1, 1))
    vif = np.ones(k) if k < 2 else np.diag(np.linalg.pinv(np.corrcoef(Z, rowvar=False)))
    return pv[1:], vif, float(np.sqrt(np.mean(scaled ** 2)))


def select(X: np.ndarray, y: np.ndarray) -> list[int]:
    """Forward inclusion (the original's select_indicators): of the candidates keeping every VIF <= 5 and every
    p <= 0.05 the one with the lowest LOO RMSE, while it lowers the error."""
    sd = X.std(axis=0)
    Z = (X - X.mean(axis=0)) / np.where(sd > 0, sd, 1.0)
    kept: list[int] = []
    error = float(np.sqrt(np.mean((y - y.mean()) ** 2)) * len(y) / (len(y) - 1))
    while True:
        trials = []
        for c in range(X.shape[1]):
            if c in kept or sd[c] == 0:
                continue
            pv, vif, rmse = strict_fit(y, Z[:, kept + [c]])
            trials.append((rmse, c, vif.max() <= VIF_LIMIT and pv.max() <= ALPHA))
        good = [x for x in trials if x[2]]
        best = min(good) if good else None
        if best is None or best[0] >= error:
            if kept or not trials:
                return kept
            return [min(good or trials)[1]]  # nothing beats the sector base: the closest stays as the input
        kept.append(best[1])
        error = best[0]


def _cv_mse(make, X: np.ndarray, y: np.ndarray, folds: int, seed: int) -> float:
    from sklearn.model_selection import KFold
    errs = []
    for tr, te in KFold(folds, shuffle=True, random_state=seed).split(X):
        errs.append(np.mean((make().fit(X[tr], y[tr]).predict(X[te]) - y[te]) ** 2))
    return float(np.mean(errs))


def fit_predict(Xtr: np.ndarray, dev: np.ndarray, Xte: np.ndarray, seed: int) -> dict[str, np.ndarray]:
    """The regression, tree and network of the deviation from the sector base on the selected indicators."""
    from sklearn.neural_network import MLPRegressor
    from sklearn.tree import DecisionTreeRegressor
    out = {}
    mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    Ztr, Zte = (Xtr - mu) / sd, (Xte - mu) / sd
    A = np.column_stack([np.ones(len(Ztr)), Ztr])
    beta = np.linalg.lstsq(A, dev, rcond=None)[0]
    out["reg"] = np.column_stack([np.ones(len(Zte)), Zte]) @ beta
    best = None
    for depth in (2, 3, 4):
        for leaf in (4, 6, 8):
            for a in (0.0, 0.01, 0.03):
                make = lambda d=depth, l=leaf, a_=a: DecisionTreeRegressor(max_depth=d, min_samples_leaf=l, ccp_alpha=a_,
                                                                           random_state=seed)
                mse = _cv_mse(make, Xtr, dev, 4, seed)
                if best is None or mse < best[0]:
                    best = (mse, make)
    out["tree"] = best[1]().fit(Xtr, dev).predict(Xte)
    ym, ys = dev.mean(), dev.std() or 1.0
    target = (dev - ym) / ys
    best = None
    for hidden in ((4,), (8,)):
        for alpha in (0.3, 1.0, 3.0):
            make = lambda h=hidden, a_=alpha, s=seed: MLPRegressor(hidden_layer_sizes=h, activation="tanh", solver="lbfgs",
                                                                   alpha=a_, max_iter=1000, random_state=s)
            mse = _cv_mse(make, Ztr, target, 3, seed)
            if best is None or mse < best[0]:
                best = (mse, hidden, alpha)
    nets = [MLPRegressor(hidden_layer_sizes=best[1], activation="tanh", solver="lbfgs", alpha=best[2], max_iter=1000,
                         random_state=seed + i).fit(Ztr, target) for i in range(5)]
    out["nn"] = np.mean([n.predict(Zte) for n in nets], axis=0) * ys + ym
    return out


def clusters(lnm: np.ndarray, comp: np.ndarray, spec: dict, seed: int) -> np.ndarray:
    """The original's companion clusters: k-means (k 2-8 by the silhouette) of z(ln m) and z(companion); a group's
    gap = sd(ln m) * (b z(companion) - z(ln m)) at its centre, b the correlation (0 if its sign is not the theory's)."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    out = np.full(len(lnm), np.nan)
    ok = np.isfinite(comp)
    if ok.sum() < 10:
        return out
    c = np.clip(comp[ok], *spec["range"])
    zl = (lnm[ok] - lnm[ok].mean()) / lnm[ok].std()
    zc = (c - c.mean()) / (c.std() or 1.0)
    F = np.column_stack([zl, zc])
    best = None
    for k in range(2, min(8, ok.sum() - 1) + 1):
        lab = KMeans(k, n_init=20, random_state=seed).fit_predict(F)
        if len(set(lab)) < 2:
            continue
        s = silhouette_score(F, lab)
        if best is None or s > best[0]:
            best = (s, lab)
    if best is None:
        return out
    b = float(np.corrcoef(zl, zc)[0, 1])
    if np.sign(b) != spec["sign"]:
        b = 0.0
    gap = np.empty(ok.sum())
    for g in set(best[1]):
        m = best[1] == g
        gap[m] = lnm[ok].std() * (b * zc[m].mean() - zl[m].mean())
    out[ok] = gap
    return out


def analyse(rows: list[dict], key: str, seed: int = SEED, folds: int = 5) -> dict | None:
    """Gaps of the four analyses and the hybrid for the companies whose multiple is in range; with the out-of-sample
    R^2 of each model and of the sector base alone (the original's quality check)."""
    from sklearn.model_selection import KFold
    spec = MULTIPLES[key]
    m = np.array([r["cap"] / r[spec["denominator"]] if r[spec["denominator"]] and r[spec["denominator"]] > 0 else np.nan
                  for r in rows])
    use = np.flatnonzero(np.isfinite(m) & (m >= spec["lo"]) & (m <= spec["hi"]))
    if len(use) < MIN_COMPANIES:
        return None
    y = np.log(m[use])
    sectors = np.array([rows[i]["sector"] for i in use])
    names = [c for c in CANDIDATES[key] if np.mean([math.isfinite(rows[i].get(c, math.nan)) for i in use]) >= COVERAGE]
    X = np.array([[rows[i].get(c, math.nan) for c in names] for i in use], float)
    est = {a: np.full(len(use), np.nan) for a in ("reg", "tree", "nn")}
    base_oos = np.full(len(use), np.nan)
    chosen: dict[str, int] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for tr, te in KFold(folds, shuffle=True, random_state=seed).split(X):
            pre = Pre().fit(X[tr])
            Xtr, Xte = pre(X[tr]), pre(X[te])
            base = SectorBase().fit(sectors[tr], y[tr])
            dev = y[tr] - base(sectors[tr])
            kept = select(Xtr, dev) if names else []
            for c in kept:
                chosen[names[c]] = chosen.get(names[c], 0) + 1
            b_te = base(sectors[te])
            base_oos[te] = b_te
            if not kept:
                for a in est:
                    est[a][te] = b_te + dev.mean()
                continue
            pred = fit_predict(Xtr[:, kept], dev, Xte[:, kept], seed)
            for a in est:
                est[a][te] = b_te + pred[a]
        comp = np.array([rows[i].get(spec["companion"], math.nan) for i in use], float)
        gaps = {a: est[a] - y for a in est}
        gaps["cl"] = clusters(y, comp, spec, seed)
    G = np.column_stack([gaps[a] for a, _ in ANALYSES])
    with np.errstate(invalid="ignore"):
        gaps["hyb"] = np.nanmean(G, axis=1)
    ss = ((y - y.mean()) ** 2).sum()
    r2 = {a: float(1 - ((est[a] - y) ** 2).sum() / ss) for a in est}
    r2["base"] = float(1 - ((base_oos - y) ** 2).sum() / ss)
    return {"companies": [rows[i]["company"] for i in use], "tickers": [rows[i]["tickers"] for i in use],
            "multiple": m[use].tolist(), "gaps": {a: v.tolist() for a, v in gaps.items()}, "r2": r2,
            "features": dict(sorted(chosen.items(), key=lambda kv: -kv[1])), "n": len(use)}


def value_date(rows: list[dict]) -> dict:
    """All multiples of one date (one BLAS thread: the dates run side by side in processes)."""
    from threadpoolctl import threadpool_limits
    out: dict = {"multiples": {}, "n": len(rows)}
    with threadpool_limits(1):
        for key in MULTIPLES:
            res = analyse(rows, key)
            if res:
                out["multiples"][key] = res
    return out


# ---------------------------------------------------------------------------- the dates, cached


FACTOR_KEYS = ([("sas_pe", "SAS P/E: гибрид"), ("sas_pe_reg", "SAS P/E: регрессия"), ("sas_pe_cl", "SAS P/E: кластеры"),
                ("sas_pe_tree", "SAS P/E: дерево"), ("sas_pe_nn", "SAS P/E: нейросеть"), ("sas_pb", "SAS P/BV: гибрид"),
                ("sas_ps", "SAS P/S: гибрид"), ("sas_pfcf", "SAS P/FCF: гибрид"), ("sas_all", "SAS: сводная оценка")])


def ticker_gaps(res: dict) -> dict[str, dict[str, float]]:
    """{ticker: {factor key: gap}} of one date's result (both shares of a company get its gap)."""
    out: dict[str, dict[str, float]] = {}
    hybrids: dict[str, list[float]] = {}
    for key, r in res["multiples"].items():
        for i, tickers in enumerate(r["tickers"]):
            for tk in tickers:
                d = out.setdefault(tk, {})
                h = r["gaps"]["hyb"][i]
                d[f"sas_{key}"] = h
                if h is not None and math.isfinite(h):
                    hybrids.setdefault(tk, []).append(h)
                if key == "pe":
                    for a, _ in ANALYSES:
                        d[f"sas_pe_{a}"] = r["gaps"][a][i]
    for tk, hs in hybrids.items():
        out[tk]["sas_all"] = float(np.mean(hs))
    return out


def _digest(rows: list[dict]) -> str:
    blob = json.dumps(rows, sort_keys=True, default=lambda x: None, allow_nan=True)
    return hashlib.sha1(f"{VERSION}:{blob}".encode()).hexdigest()[:16]


def _cache_path():
    return data_dir() / f"valuation-v{VERSION}.json"


def valuations(p: universe.Panel, weeks: list[int], M: np.ndarray, progress=None) -> dict[str, dict]:
    """{date: value_date result} for the panel weeks, from the disk cache where the inputs are unchanged; the rest
    computed side by side in processes."""
    reps = sas.reports() or {}
    if not reps:
        return {}
    sector_of = sas.sectors()
    path = _cache_path()
    cache: dict = {}
    if path.exists():
        try:
            cache = json.loads(path.read_text())
        except ValueError:
            cache = {}
    todo, out = [], {}
    for t in weeks:
        day = p.dates[t]
        if day < "2022-01-01":
            continue
        rows = companies(p, t, M, reps, sector_of)
        if len(rows) < MIN_COMPANIES:
            continue
        key = _digest(rows)
        hit = cache.get(day)
        if hit and hit.get("key") == key:
            out[day] = hit["result"]
        else:
            todo.append((day, key, rows))
    if todo:
        workers = max(1, min(len(todo), (os.cpu_count() or 2) - 1, 8))
        with single_thread_pool(workers) as pool:
            for (day, key, _), res in zip(todo, pool.map(value_date, [r for _, _, r in todo])):
                cache[day] = {"key": key, "result": res}
                out[day] = res
                if progress:
                    progress(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, allow_nan=True))
    return out


def sas_classes(day: str) -> dict[str, dict[str, tuple[float, float]]] | None:
    """server-analytic-system's P/E classes of its snapshot `day`: {analysis: {ticker: (gap, multiple)}}."""
    import csv
    root = sas.sas_dir()
    path = root / f"stock_snapshot_{day}" / "pe" / "classes.csv" if root else None
    if path is None or not path.exists():
        return None
    theirs: dict[str, dict[str, tuple[float, float]]] = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                theirs.setdefault(r["analysis"], {})[r["ticker"]] = (float(r["valuation_gap"]), float(r["multiple"]))
            except ValueError:
                continue
    return theirs


def parity(res: dict, day: str) -> dict | None:
    """Our P/E valuation `res` (analyse's result) of `day` against server-analytic-system's snapshot of that day: the
    Spearman correlation of the multiples and of each analysis's gap over the companies both valued."""
    theirs = sas_classes(day)
    if not theirs or not res:
        return None
    ours = {tk: i for i, tks in enumerate(res["tickers"]) for tk in tks}
    names = {"regression": "reg", "cluster": "cl", "tree": "tree", "neural": "nn", "hybrid": "hyb"}
    common = [tk for tk in theirs.get("hybrid", {}) if tk in ours]
    a = np.array([res["multiple"][ours[tk]] for tk in common])
    b = np.array([theirs["hybrid"][tk][1] for tk in common])
    out = {"day": day, "ours": res["n"], "theirs": len(theirs.get("hybrid", {})), "common": len(common),
           "multiple_rho": float(stats.spearmanr(a, b)[0]) if len(common) > 5 else None,
           "multiple_median_ratio": float(np.median(a / b)) if len(common) else None, "analyses": {}}
    for theirs_name, our in names.items():
        pairs = [(res["gaps"][our][ours[tk]], v[0]) for tk, v in theirs.get(theirs_name, {}).items() if tk in ours]
        pairs = [(x, y) for x, y in pairs if x is not None and math.isfinite(x) and math.isfinite(y)]
        if len(pairs) > 5:
            x, y = zip(*pairs)
            out["analyses"][theirs_name] = {"n": len(pairs), "rho": float(stats.spearmanr(x, y)[0])}
    return out


def compare_with_sas(p: universe.Panel, day: str, M: np.ndarray) -> dict | None:
    """parity() of a fresh valuation of `day` (the panel week of that date)."""
    if day not in p.dates or sas_classes(day) is None:
        return None
    t = p.dates.index(day)
    res = analyse(companies(p, t, M, sas.reports() or {}, sas.sectors()), "pe")
    out = parity(res, day)
    if out:
        out["r2"], out["features"] = res["r2"], res["features"]
    return out


def summary(vals: dict[str, dict]) -> dict:
    """Over the dates: the companies valued, each model's out-of-sample R^2 of ln m by multiple and month, how often
    each indicator was selected (share of the folds), and the parity with server-analytic-system's own snapshots."""
    days = sorted(vals)
    out: dict = {"dates": days, "multiples": {}, "parity": []}
    for key, spec in MULTIPLES.items():
        r2 = {a: [] for a in ("reg", "tree", "nn", "base")}
        n, chosen = [], {}
        for d in days:
            res = vals[d]["multiples"].get(key)
            for a in r2:
                r2[a].append(res["r2"][a] if res else None)
            n.append(res["n"] if res else None)
            if res:
                for f, c in res["features"].items():
                    chosen[f] = chosen.get(f, 0) + c
        folds = 5 * sum(1 for x in n if x)
        out["multiples"][key] = {"label": spec["label"], "n": n, "r2": r2,
                                 "r2_mean": {a: float(np.nanmean([x for x in v if x is not None])) if any(x is not None for x in v)
                                             else None for a, v in r2.items()},
                                 "features": {f: c / folds for f, c in sorted(chosen.items(), key=lambda kv: -kv[1])} if folds else {}}
    root = sas.sas_dir()
    for snap in sorted(root.glob("stock_snapshot_*")) if root else []:
        day = snap.name.removeprefix("stock_snapshot_")
        if day in vals and vals[day]["multiples"].get("pe"):
            par = parity(vals[day]["multiples"]["pe"], day)
            if par:
                out["parity"].append(par)
    return out


def mcftr_weekly(p: universe.Panel) -> np.ndarray:
    from . import sources
    from .assets import ffill_on
    try:
        mc = sources.load("moex:index:MCFTR")
    except Exception:  # noqa: BLE001
        return np.full(len(p.dates), np.nan)
    px = ffill_on(mc.dates, mc.values, p.dates)
    return np.r_[np.nan, px[1:] / px[:-1] - 1]

