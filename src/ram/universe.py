"""The MOEX share market week by week: every share of the main board TQBR (shares and depositary receipts) on the last
trading day of each week up to Friday, from ISS's history by date. The shares delisted since are in it, so a cross-section
of a past date has no survivorship bias - unlike a list of today's tickers.

The panel is on today's share count (ISS's splits and the round jumps ISS does not list, see sources.unlisted_splits)
and the weekly return holds the dividends of server-analytic-system's T-Invest data: (P_t + D) / P_{t-1} - 1.
"""
from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from . import sas, sources
from .net import fetch_json
from .store import data_dir

ISS_DAY = ("https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities.json?iss.meta=off"
           "&date={day}&history.columns=TRADEDATE,SECID,SHORTNAME,LEGALCLOSEPRICE,CLOSE,WAPRICE,VALUE,NUMTRADES")
FIRST_YEAR = 2013  # TQBR opened in March 2013


def iss_day(day: str) -> list[list]:
    """[secid, short name, price, traded value in rubles] of every TQBR share on `day` (empty on a holiday)."""
    url = ISS_DAY.format(day=day)
    first = fetch_json(url + "&start=0")
    cols, rows = first["history"]["columns"], list(first["history"]["data"])
    cur = dict(zip(first["history.cursor"]["columns"], first["history.cursor"]["data"][0]))
    for start in range(int(cur["PAGESIZE"]), int(cur["TOTAL"]), int(cur["PAGESIZE"])):
        rows += fetch_json(f"{url}&start={start}")["history"]["data"]
    ix = {c: i for i, c in enumerate(cols)}
    out = []
    for r in rows:
        price = next((r[ix[c]] for c in ("LEGALCLOSEPRICE", "CLOSE", "WAPRICE") if r[ix[c]] and r[ix[c]] > 0), None)
        if price is None:
            continue
        out.append([r[ix["SECID"]], r[ix["SHORTNAME"]], float(price), float(r[ix["VALUE"]] or 0)])
    return out


def week_session(friday: date) -> tuple[str, list[list]]:
    """The last trading day of the week (Friday back to Monday) and its rows; ("", []) for a week without one."""
    for back in range(5):
        day = (friday - timedelta(days=back)).isoformat()
        rows = iss_day(day)
        if rows and sum(r[3] for r in rows) > 0:
            return day, rows
    return "", []


def fridays(first: date, last: date) -> list[date]:
    d = first + timedelta(days=(4 - first.weekday()) % 7)
    out = []
    while d <= last:
        out.append(d)
        d += timedelta(days=7)
    return out


def _year_path(year: int):
    return data_dir() / f"tqbr-weeks-{year}.json"


def load_weeks(year_from: int = FIRST_YEAR, progress=None) -> dict[str, tuple[str, list[list]]]:
    """{friday: (session day, rows)} from `year_from` to the last finished week; a year's file is kept on disk and only
    the weeks missing from it are fetched (a past week does not change)."""
    today = date.today()
    out: dict[str, tuple[str, list[list]]] = {}
    for year in range(max(year_from, FIRST_YEAR), today.year + 1):
        path = _year_path(year)
        have: dict = {}
        if path.exists():
            try:
                have = json.loads(path.read_text())
            except ValueError:
                have = {}
        want = [f for f in fridays(date(year, 1, 1), min(date(year, 12, 31), today - timedelta(days=1)))
                if f.isoformat() not in have]
        if want:
            with ThreadPoolExecutor(8) as pool:
                for f, got in zip(want, pool.map(week_session, want)):
                    have[f.isoformat()] = list(got)
                    if progress:
                        progress(f.isoformat())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(have, ensure_ascii=False))
        out.update({k: tuple(v) for k, v in have.items()})
    return dict(sorted(out.items()))


@dataclass
class Panel:
    dates: list[str]  # session days, one a week
    tickers: list[str]
    names: dict[str, str]
    P: np.ndarray  # T x N price on today's share count, NaN where the share is not on the board that week
    V: np.ndarray  # T x N traded value of that day, rubles
    R: np.ndarray  # T x N total return since the share's previous week on the board (NaN when it was not there)
    D: np.ndarray  # T x N dividends that left the price during the week (today's share count)
    covered: np.ndarray  # N: the share is in server-analytic-system's T-Invest list, so its dividends are known
    notes: list[str] = field(default_factory=list)

    def col(self, ticker: str) -> int:
        return self.tickers.index(ticker)


_panel: tuple[float, int, Panel] | None = None


def panel(year_from: int = FIRST_YEAR, max_age_hours: float = 12, progress=None) -> Panel:
    global _panel
    if _panel and _panel[1] <= year_from and time.time() - _panel[0] < max_age_hours * 3600:
        return _panel[2]
    weeks = load_weeks(year_from, progress)
    days = [d for d, rows in weeks.values() if d]
    rows_by = [rows for d, rows in weeks.values() if d]
    tickers = sorted({r[0] for rows in rows_by for r in rows})
    col = {t: j for j, t in enumerate(tickers)}
    T, N = len(days), len(tickers)
    raw, V = np.full((T, N), np.nan), np.zeros((T, N))
    names: dict[str, str] = {}
    for i, rows in enumerate(rows_by):
        for secid, name, price, value in rows:
            j = col[secid]
            raw[i, j], V[i, j] = price, value
            names[secid] = name
    splits = sources.moex_splits()
    divs = sas.dividends() or {}
    covered_set = sas.covered()
    P = np.full((T, N), np.nan)
    R = np.full((T, N), np.nan)
    D = np.zeros((T, N))
    found_all = []
    for j, t in enumerate(tickers):
        on = np.flatnonzero(np.isfinite(raw[:, j]))
        if not len(on):
            continue
        d_on = [days[i] for i in on]
        k = sources.shares_today(splits.get(t, []), d_on)
        px, found = sources.unlisted_splits(d_on, raw[on, j] / k, jump=9.0)
        found_all += [f"{t} {d} ×{sources._ratio_text(c)}" for d, c in found]
        P[on, j] = px
        cash = np.zeros(len(on))
        for dv in divs.get(t, []):
            day = dv.last_buy or dv.record
            # the price drops the next trading day: in the week whose session comes after the last day to buy
            m = int(np.searchsorted(np.array(d_on), day, side="right"))
            if 0 < m < len(on):
                amount = sources.dividend_rubles(dv, d_on[m])
                if math.isfinite(amount):
                    cash[m] += amount
        D[on, j] = cash
        R[on[1:], j] = (px[1:] + cash[1:]) / px[:-1] - 1
    notes = []
    if found_all:
        notes.append("сплиты не из списка ISS (скачок недельной цены в круглое число раз): " + ", ".join(found_all[:12])
                     + (f" и ещё {len(found_all) - 12}" if len(found_all) > 12 else ""))
    covered = np.array([t in covered_set for t in tickers]) if covered_set else np.zeros(N, bool)
    p = Panel(dates=days, tickers=tickers, names=names, P=P, V=V, R=R, D=D, covered=covered, notes=notes)
    _panel = (time.time(), year_from, p)
    return p
