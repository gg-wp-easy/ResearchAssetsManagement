"""Checks of the portfolios at hand against the exchange's events (events.py): server-analytic-system's share
portfolios (the presets), the book's current share picks and server-analytic-system's latest bond portfolios. For
each: what to sell (exclude), what to look at (warn), and the weights recomputed without the excluded positions."""
from __future__ import annotations

import csv

from . import events, sas
from .presets import SAS_MAX_SHARPE, SAS_MIN_RISK


def _check(title: str, key: str, source: str, day: str | None, rows: list[dict], evs, link: str | None = None) -> dict:
    codes = [r["code"] for r in rows]
    found = events.check(codes, evs)
    keep = [r for r in rows if found[r["code"]]["status"] != "exclude"]
    total = sum(r["weight"] for r in keep) or 1.0
    positions = []
    for r in rows:
        c = found[r["code"]]
        positions.append({**r, "status": c["status"], "issuer": c["issuer"], "events": c["events"][:4],
                          "after": r["weight"] / total if c["status"] != "exclude" else 0.0})
    drop = [r["code"] for r in rows if found[r["code"]]["status"] == "exclude"]
    return {"key": key, "title": title, "source": source, "date": day, "positions": positions,
            "excluded": len(drop), "warned": sum(1 for p in positions if p["status"] == "warn"),
            "excluded_weight": sum(r["weight"] for r in rows if r["code"] in drop), "drop": drop, "link": link}


def sas_bond_portfolios() -> list[tuple[str, str, list[dict]]]:
    """server-analytic-system's latest bond portfolios: [(label, date, [{code, name, weight, issuer_name}])]."""
    root = sas.sas_dir()
    if root is None:
        return []
    files = sorted((root / "notebook_reports" / "bonds" / "portfolios").glob("portfolios_*.csv"))
    if not files:
        return []
    groups: dict[str, list[dict]] = {}
    with files[-1].open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                w = float(row.get("weight") or 0)
            except ValueError:
                continue
            groups.setdefault(row.get("label") or row.get("portfolio") or "?", []).append(
                {"code": row["ticker"], "name": row.get("name") or row["ticker"], "weight": w,
                 "issuer_name": row.get("issuer_name") or ""})
    day = files[-1].stem.split("_")[-1]
    return [(label, day, rows) for label, rows in groups.items()]


def portfolios() -> dict:
    evs, cov = events.all_events()
    out = []
    for key, title, rows in (("sas_max_sharpe", "SAS: максимум Шарпа (акции)", SAS_MAX_SHARPE),
                             ("sas_min_risk", "SAS: минимум риска (акции)", SAS_MIN_RISK)):
        res = _check(title, key, "пресет — портфель server-analytic-system на 31.10.2025", "2025-10-31",
                     [{"code": t, "name": n, "weight": w} for t, n, w in rows], evs)
        res["link"] = f"#/explore/rule?preset={key}" + (f"&drop={','.join(res['drop'])}" if res["drop"] else "")
        out.append(res)
    try:
        from . import book
        d = book.data(0.002)
        o = book.Opts()
        form = max((k for k in d.picks.get(o.equity, {})), default=None)
        if form is not None:
            picks = d.picks[o.equity][form]
            out.append(_check("Портфель из блоков: акции отбора", "book", "отбор по моментуму, низкой волатильности, "
                              "E/P и FCF/P, поровну", d.dates[form],
                              [{"code": t, "name": d.names.get(t, t), "weight": 1 / len(picks)} for t in picks], evs,
                              "#/book"))
    except Exception as e:  # noqa: BLE001 - the panel is not built yet: the other portfolios still count
        out.append({"key": "book", "title": "Портфель из блоков: акции отбора", "error": str(e), "positions": []})
    for label, day, rows in sas_bond_portfolios():
        out.append(_check(f"SAS: облигации — {label}", f"sas_bonds_{label}", "последний файл портфелей облигаций "
                          "server-analytic-system", day, rows, evs))
    return {"coverage": cov, "portfolios": out}
