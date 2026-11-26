"""Data of the server-analytic-system project (`../server-analytic-system/data`, or the folder in RAM_SAS_DATA).

- `tbank_dividends.csv` - T-Invest dividend events from 2019: the amount per share on today's share count (T-Invest
  restates the history after splits: GMKN's 2019 dividend is 7.93, not 792.5), the last day to buy with the right;
- `smartlab_financials.csv` - smart-lab.ru annual reports (IFRS and RAS, mostly the years 2021-2025) with the day each
  was published, per-share values on today's share count as well.

Optional: without the folder MOEX shares stay price returns and the factor lab has only the price factors.
"""
from __future__ import annotations

import csv
import math
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path


def sas_dir() -> Path | None:
    env = os.environ.get("RAM_SAS_DATA")
    path = Path(env) if env else Path(__file__).resolve().parents[2].parent / "server-analytic-system" / "data"
    return path if path.is_dir() else None


_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _read(name: str, parse):
    """`parse(rows)` of a CSV of the folder, kept while the file is unchanged; None without the file."""
    root = sas_dir()
    path = root / name if root else None
    if path is None or not path.exists():
        return None
    mtime = path.stat().st_mtime
    with _lock:
        hit = _cache.get(name)
        if hit and hit[0] == mtime:
            return hit[1]
    with path.open(newline="", encoding="utf-8") as f:
        value = parse(list(csv.DictReader(f)))
    with _lock:
        _cache[name] = (mtime, value)
    return value


def _float(x: str | None) -> float:
    try:
        v = float(x) if x not in (None, "") else math.nan
    except ValueError:
        return math.nan
    return v


@dataclass(frozen=True)
class Dividend:
    last_buy: str  # the last day to buy with the right; the share trades without it from the next trading day
    record: str
    amount: float  # per share, on today's share count, before tax
    currency: str  # rub | usd ...


def dividends() -> dict[str, list[Dividend]] | None:
    def parse(rows: list[dict]) -> dict[str, list[Dividend]]:
        out: dict[str, set[Dividend]] = {}
        for r in rows:
            amount = _float(r.get("dividend_net"))
            record = (r.get("record_date") or "")[:10]
            if not record or not amount > 0:
                continue
            last_buy = (r.get("last_buy_date") or "")[:10]
            d = Dividend(last_buy=last_buy, record=record, amount=amount, currency=(r.get("currency") or "rub").lower())
            out.setdefault(r["ticker"].strip().upper(), set()).add(d)
        return {t: sorted(v, key=lambda d: d.record) for t, v in out.items()}
    return _read("tbank_dividends.csv", parse)


DIVIDENDS_FROM = "2019-01-01"  # T-Invest's history starts here: earlier payments are unknown, not absent


def covered() -> set[str]:
    """Tickers of server-analytic-system's share list (today's rouble shares of T-Invest): their dividends are known
    from 2019; a share outside it (delisted, say) may have paid without a trace here."""
    return set(reports() or {}) | set(dividends() or {})


@dataclass
class Report:
    ticker: str
    page: str  # smart-lab's company page: the ordinary and the preferred share of a company share it
    standard: str  # MSFO | RSBU
    period: str  # the year
    published: str  # the day the report came out
    values: dict[str, float] = field(default_factory=dict)

    def get(self, *names: str) -> float:
        for n in names:
            v = self.values.get(n, math.nan)
            if math.isfinite(v):
                return v
        return math.nan


def reports() -> dict[str, list[Report]] | None:
    """Annual reports by ticker (the last twelve months' "LTM" column is left out: it is only today's)."""
    def parse(rows: list[dict]) -> dict[str, list[Report]]:
        by: dict[tuple[str, str, str], Report] = {}
        for r in rows:
            period, published = r.get("period") or "", (r.get("report_date") or "")[:10]
            if not period.isdigit() or not published:
                continue
            key = (r["ticker"], r["standard"], period)
            rep = by.get(key)
            if rep is None:
                rep = by[key] = Report(ticker=r["ticker"].strip().upper(), page=(r.get("page") or "").strip().upper(),
                                       standard=r["standard"], period=period, published=published)
            rep.published = max(rep.published, published)
            v = _float(r.get("value"))
            if math.isfinite(v):
                rep.values[r["field"]] = v
        out: dict[str, list[Report]] = {}
        for rep in by.values():
            out.setdefault(rep.ticker, []).append(rep)
        for v in out.values():
            v.sort(key=lambda x: (x.published, x.period))
        return out
    return _read("smartlab_financials.csv", parse)


def report_as_of(reps: list[Report], day: str, max_age_days: int = 550) -> Report | None:
    """The latest annual report published before `day` (IFRS over RAS for the same year), not older than
    `max_age_days` from the end of its year to `day` (as server-analytic-system's snapshots)."""
    from datetime import date
    best: Report | None = None
    for r in reps:
        if r.published >= day:
            continue
        if (date.fromisoformat(day) - date(int(r.period), 12, 31)).days > max_age_days:
            continue
        rank = (r.period, r.standard == "MSFO", r.published)
        if best is None or rank > (best.period, best.standard == "MSFO", best.published):
            best = r
    return best
