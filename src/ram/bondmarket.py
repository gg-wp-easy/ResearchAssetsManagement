"""MOEX's bond market week by week (ISS), for a bond sleeve built from single issues instead of a fund.

* Weekly cross-sections: every bond of the secondary market's order-book boards ("безадрес.": T0 boards to 2019, T+
  after; the defaulted bonds' sector "Облигации Д" included, so a default shows as a price) on the last trading day of
  each week, from 2011 - with the bonds redeemed or defaulted since, so a past date has no survivorship bias. One row a
  bond: its busiest board that day. Price in % of the face, accrued interest and face in the face's currency (the
  face of an OFZ-IN is indexed to inflation; an amortised bond's face falls).
* The catalogue (`securities`): type (ofz_bond, corporate_bond, exchange_bond, subfederal_bond, ...) and issuer of
  every bond ISS knows, the redeemed ones included.
* Payment schedules (`schedules`, ISS bondization): coupons with their rates, amortisations and the redemption, offers.
  A floater's past coupons are there too; only its future ones are unknown.
* The zero-coupon OFZ curve (`curve`, КБД/G-curve, from 2014-01-06): MOEX's published effective annual yields at
  0.25 ... 30 years on each session day.

Files in data/cache: bonds-weeks-<year>.json.gz (a past week is not fetched again), bond-schedules-v1.json.gz (a
redeemed bond's schedule is final; a live one is refreshed after a week), zcyc-v1.json.
"""
from __future__ import annotations

import gzip
import json
import math
import time
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .net import NotFound, fetch_json
from .store import cached_json, data_dir
from .universe import fridays

ISS = "https://iss.moex.com/iss"
COLS = ("BOARDID", "SECID", "SHORTNAME", "NUMTRADES", "VALUE", "LEGALCLOSEPRICE", "CLOSE", "WAPRICE", "MARKETPRICE3",
        "ACCINT", "YIELDCLOSE", "DURATION", "MATDATE", "OFFERDATE", "FACEVALUE", "FACEUNIT")
HISTORY = (f"{ISS}/history/engines/stock/markets/bonds/securities.json?iss.meta=off&date={{day}}"
           f"&history.columns={','.join(COLS)}")
FIRST_YEAR = 2011
CURVE_FROM = "2014-01-06"  # ISS's zcyc archive starts here
RUB = {"RUB", "RUR", "SUR"}
# A row: secid, board, price % of face, accrued interest, face, traded value (rubles), trades, yield % (effective, to
# maturity or the offer), duration (days), maturity, offer date - the last three may be None.
ROW = ("secid", "board", "price", "accint", "face", "value", "trades", "ytm", "duration", "matdate", "offerdate", "unit")


def boards() -> dict[str, str]:
    """{board: title} of the bond market's boards, the closed ones included."""
    def get() -> dict:
        j = fetch_json(f"{ISS}/engines/stock/markets/bonds/boards.json?iss.meta=off")
        ix = {c: i for i, c in enumerate(j["boards"]["columns"])}
        return {r[ix["boardid"]]: r[ix["title"]] for r in j["boards"]["data"]}
    return cached_json("iss-bond-boards", get, max_age_hours=24 * 30)  # type: ignore[return-value]


def order_book(title: str) -> bool:
    """A secondary-market order-book board: not a placement or buy-back auction, a negotiated deal, a block trade or
    an ETC."""
    t = title.lower()
    return "безадрес" in t and not any(w in t for w in ("крупные пакеты", "аукцион", "etc"))


def defaulted_board(title: str) -> bool:
    return "облигации д" in title.lower()  # "Сектор Д": bonds in default trade there


def qualified_board(title: str) -> bool:
    return "пир" in title.lower()  # "повышенного инвестиционного риска": for qualified investors


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def iss_day(day: str, keep: set[str]) -> tuple[list[list], dict[str, str]]:
    """The rows of `day` (one a bond, its busiest board among `keep`) and the short names; ([], {}) on a holiday."""
    url = HISTORY.format(day=day)
    first = fetch_json(url + "&start=0")
    rows = list(first["history"]["data"])
    cur = dict(zip(first["history.cursor"]["columns"], first["history.cursor"]["data"][0]))
    for start in range(int(cur["PAGESIZE"]), int(cur["TOTAL"]), int(cur["PAGESIZE"])):
        rows += fetch_json(f"{url}&start={start}")["history"]["data"]
    ix = {c: i for i, c in enumerate(first["history"]["columns"])}
    best: dict[str, tuple] = {}
    names: dict[str, str] = {}
    for r in rows:
        board = r[ix["BOARDID"]]
        if board not in keep:
            continue
        price = next((p for c in ("LEGALCLOSEPRICE", "CLOSE", "WAPRICE", "MARKETPRICE3")
                      if (p := _num(r[ix[c]])) and p > 0), None)
        face = _num(r[ix["FACEVALUE"]])
        if price is None or not face:
            continue
        trades, value = int(r[ix["NUMTRADES"]] or 0), _num(r[ix["VALUE"]]) or 0.0
        unit = str(r[ix["FACEUNIT"]] or "RUB").upper()
        row = [r[ix["SECID"]], board, price, _num(r[ix["ACCINT"]]) or 0.0, face, value, trades,
               _num(r[ix["YIELDCLOSE"]]), _num(r[ix["DURATION"]]), r[ix["MATDATE"]] or None, r[ix["OFFERDATE"]] or None,
               "RUB" if unit in RUB else unit]
        key = (trades > 0, value)
        sid = row[0]
        if sid not in best or key > best[sid][0]:
            best[sid] = (key, row)
        names.setdefault(sid, r[ix["SHORTNAME"]] or sid)
    return [b[1] for b in best.values()], names


def week_session(friday: date, keep: set[str]) -> tuple[str, list[list], dict[str, str]]:
    """The last trading day of the week (Friday back to Monday), its rows and names; ("", [], {}) without one."""
    for back in range(5):
        day = (friday - timedelta(days=back)).isoformat()
        rows, names = iss_day(day, keep)
        if rows and sum(r[5] for r in rows) > 0:
            return day, rows, names
    return "", [], {}


def _year_path(year: int):
    return data_dir() / f"bonds-weeks-{year}.json.gz"


def _read_gz(path) -> dict:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_gz(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


def load_year(year: int, keep: set[str] | None = None, progress=None) -> tuple[dict[str, list], dict[str, str]]:
    """({friday: [session day, rows]}, {secid: short name}) of one year: the file, and the finished weeks missing from
    it fetched and saved."""
    today = date.today()
    keep = keep if keep is not None else {b for b, t in boards().items() if order_book(t)}
    path = _year_path(year)
    blob = _read_gz(path) if path.exists() else {}
    have, nm = blob.get("weeks", {}), blob.get("names", {})
    want = [f for f in fridays(date(year, 1, 1), min(date(year, 12, 31), today - timedelta(days=1)))
            if f.isoformat() not in have]
    if want:
        with ThreadPoolExecutor(8) as pool:
            for f, (day, rows, n) in zip(want, pool.map(lambda f: week_session(f, keep), want)):
                have[f.isoformat()] = [day, rows]
                nm.update(n)
                if progress:
                    progress(f.isoformat())
        _write_gz(path, {"v": 1, "weeks": have, "names": nm})
    return have, nm


def load_weeks(year_from: int = FIRST_YEAR, progress=None) -> tuple[dict[str, tuple[str, list[list]]], dict[str, str]]:
    """({friday: (session day, rows)}, {secid: short name}) from `year_from` to the last finished week."""
    keep = {b for b, t in boards().items() if order_book(t)}
    out: dict[str, tuple[str, list[list]]] = {}
    names: dict[str, str] = {}
    for year in range(max(year_from, FIRST_YEAR), date.today().year + 1):
        have, nm = load_year(year, keep, progress)
        out.update({k: (v[0], v[1]) for k, v in have.items()})
        names.update(nm)
    return dict(sorted(out.items())), names


def securities() -> dict[str, dict]:
    """{secid: {isin, type, emitent, emitent_id, inn, board}} of every bond ISS lists (traded now or not)."""
    cols = "secid,isin,emitent_id,emitent_title,emitent_inn,type,primary_boardid"

    def get() -> dict:
        out: dict[str, dict] = {}
        for trading in (1, 0):
            start = 0
            while True:
                j = fetch_json(f"{ISS}/securities.json?engine=stock&market=bonds&is_trading={trading}&iss.meta=off"
                               f"&limit=100&start={start}&securities.columns={cols}")
                rows = j["securities"]["data"]
                for sid, isin, eid, etitle, inn, kind, board in rows:
                    out[sid] = {"isin": isin, "emitent_id": eid, "emitent": etitle or "", "inn": inn or "",
                                "type": kind or "", "board": board or ""}
                if len(rows) < 100:
                    break
                start += 100
        return out
    return cached_json("iss-bond-securities", get, max_age_hours=24 * 7)  # type: ignore[return-value]


# --- payment schedules ---------------------------------------------------------------------------------------------

SCHEDULES = "bond-schedules-v1.json.gz"


def bondization(secid: str) -> dict:
    """{coupons: [[date, amount, rate %]], amort: [[date, amount]], offers: [[date, kind]]}: amounts a bond in its
    face currency (None where not set yet: a floater's future coupons)."""
    j = fetch_json(f"{ISS}/securities/{secid}/bondization.json?iss.meta=off&iss.only=coupons,amortizations,offers"
                   "&limit=unlimited")

    def table(name: str) -> list[dict]:
        t = j.get(name) or {"columns": [], "data": []}
        return [dict(zip(t["columns"], r)) for r in t["data"]]

    coupons = [[c["coupondate"], _num(c["value"]), _num(c["valueprc"])] for c in table("coupons") if c.get("coupondate")]
    amort = [[a["amortdate"], _num(a["value"])] for a in table("amortizations") if a.get("amortdate")]
    offers = [[o["offerdate"], o.get("offertype") or ""] for o in table("offers") if o.get("offerdate")]
    return {"coupons": sorted(coupons), "amort": sorted(amort), "offers": sorted(offers)}


def schedules(secids, progress=None) -> dict[str, dict]:
    """The schedules of `secids` (cached; a redeemed bond's never again, a live one's after a week)."""
    path = data_dir() / SCHEDULES
    have: dict = _read_gz(path) if path.exists() else {}
    now, today = time.time(), date.today().isoformat()

    def stale(s: str) -> bool:
        h = have.get(s)
        if not h:
            return True
        last = max([a[0] for a in h["amort"]] + [c[0] for c in h["coupons"]] or [""])
        return last >= today and now - h.get("fetched", 0) > 7 * 86400

    want = sorted({s for s in secids if stale(s)})
    if want:
        def job(s: str):
            try:
                return s, bondization(s)
            except NotFound:
                return s, {"coupons": [], "amort": [], "offers": []}
            except Exception:  # noqa: BLE001 - one schedule did not load: asked again next time
                return s, None
        with ThreadPoolExecutor(8) as pool:
            for i, (s, got) in enumerate(pool.map(job, want)):
                if got is not None:
                    have[s] = {**got, "fetched": now}
                if progress and i % 100 == 0:
                    progress(f"графики выплат: {i}/{len(want)}")
        _write_gz(path, have)
    return {s: have[s] for s in secids if s in have}


# --- the zero-coupon OFZ curve -------------------------------------------------------------------------------------

def _zcyc_day(day: str) -> list[list[float]]:
    j = fetch_json(f"{ISS}/engines/stock/zcyc.json?date={day}&iss.only=yearyields&iss.meta=off")
    t = j["yearyields"]
    ix = {c: i for i, c in enumerate(t["columns"])}
    return [[float(r[ix["period"]]), float(r[ix["value"]]) / 100] for r in t["data"]
            if r[ix["tradedate"]] == day and r[ix["value"]] is not None]


def curve(days: list[str]) -> dict[str, list[list[float]]]:
    """{day: [[years, effective annual yield]]} of the КБД on the session days from 2014-01-06 (empty before)."""
    path = data_dir() / "zcyc-v1.json"
    try:
        have = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        have = {}
    want = [d for d in days if d >= CURVE_FROM and d not in have]
    if want:
        with ThreadPoolExecutor(8) as pool:
            for d, got in zip(want, pool.map(_zcyc_day, want)):
                have[d] = got
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(have))
    return {d: have.get(d, []) for d in days}


def curve_yield(points: list[list[float]], years: float) -> float | None:
    """The КБД's yield at `years` (linear between the published terms, flat beyond them)."""
    if not points:
        return None
    xs = [p[0] for p in points]
    if years <= xs[0]:
        return points[0][1]
    if years >= xs[-1]:
        return points[-1][1]
    i = bisect_right(xs, years)
    (x0, y0), (x1, y1) = points[i - 1], points[i]
    return y0 + (y1 - y0) * (years - x0) / (x1 - x0)


# --- the market in one long table ----------------------------------------------------------------------------------

def _ordinal(day: str | None) -> int:
    if not day or day.startswith("0000"):
        return 0
    try:
        return date.fromisoformat(day[:10]).toordinal()
    except ValueError:
        return 0


@dataclass
class Market:
    """Every week's bonds in one long table sorted by bond, then week: row k is bond `sid[k]` in week `t[k]`.
    `cross_section(m, t)` gives week t's rows, `at(s, t)` a bond's row."""
    dates: list[str]  # session days
    secids: list[str]
    names: dict[str, str]
    boards: list[str]
    units: list[str]
    t: np.ndarray
    sid: np.ndarray
    board: np.ndarray  # index into boards
    unit: np.ndarray  # index into units
    price: np.ndarray  # % of face
    accint: np.ndarray
    face: np.ndarray
    value: np.ndarray  # traded, rubles
    trades: np.ndarray
    ytm: np.ndarray  # effective annual, NaN when ISS has none
    duration: np.ndarray  # years, NaN when ISS has none
    mat: np.ndarray  # date ordinals, 0 when unknown
    offer: np.ndarray
    start: np.ndarray
    by_week: np.ndarray  # row indices sorted by week: week t's are by_week[start[t]:start[t+1]]
    curves: list[list[list[float]]] = field(default_factory=list)  # the КБД of each session day
    _key: np.ndarray | None = None

    def week(self, t: int) -> slice:
        return slice(int(self.start[t]), int(self.start[t + 1]))

    def at(self, s: int, t: int) -> int:
        """Row of bond index `s` in week `t`, -1 when it was not on the market that week."""
        if self._key is None:
            self._key = self.sid.astype(np.int64) * len(self.dates) + self.t
        k = int(s) * len(self.dates) + int(t)
        i = int(np.searchsorted(self._key, k))
        return i if i < len(self._key) and self._key[i] == k else -1

    def col(self, secid: str) -> int:
        return self.secids.index(secid)


_market: tuple[float, int, Market] | None = None


def market(year_from: int = FIRST_YEAR, max_age_hours: float = 12, progress=None) -> Market:
    """The weekly table from `year_from` (kept in memory for `max_age_hours`), with the КБД of each week. A year at a
    time: its rows become arrays before the next year is read (the lists of all years took ~0.5 GB)."""
    global _market
    if _market and _market[1] <= year_from and time.time() - _market[0] < max_age_hours * 3600:
        return _market[2]
    keep = {b for b, t in boards().items() if order_book(t)}
    days: list[str] = []
    names: dict[str, str] = {}
    col: dict[str, int] = {}
    bcol: dict[str, int] = {}
    ucol: dict[str, int] = {}
    parts: dict[str, list[np.ndarray]] = {k: [] for k in ("t", "sid", "board", "unit", "price", "accint", "face",
                                                           "value", "trades", "ytm", "duration", "mat", "offer")}

    def num(rows: list[list], i: int, scale: float = 1.0) -> np.ndarray:
        return np.fromiter((np.nan if r[i] is None else float(r[i]) * scale for r in rows), np.float64, len(rows))

    for year in range(max(year_from, FIRST_YEAR), date.today().year + 1):
        have, nm = load_year(year, keep, progress)
        names.update(nm)
        for _, (day, rows) in sorted(have.items()):
            if not day:
                continue
            t, n = len(days), len(rows)
            days.append(day)
            parts["t"].append(np.full(n, t, np.int32))
            parts["sid"].append(np.fromiter((col.setdefault(r[0], len(col)) for r in rows), np.int32, n))
            parts["board"].append(np.fromiter((bcol.setdefault(r[1], len(bcol)) for r in rows), np.int16, n))
            parts["unit"].append(np.fromiter((ucol.setdefault(r[11], len(ucol)) for r in rows), np.int16, n))
            for key, i, scale in (("price", 2, 1.0), ("accint", 3, 1.0), ("face", 4, 1.0), ("value", 5, 1.0),
                                  ("trades", 6, 1.0), ("ytm", 7, 0.01), ("duration", 8, 1 / 365.25)):
                parts[key].append(num(rows, i, scale))
            parts["mat"].append(np.fromiter((_ordinal(r[9]) for r in rows), np.int32, n))
            parts["offer"].append(np.fromiter((_ordinal(r[10]) for r in rows), np.int32, n))
        del have
    a = {k: np.concatenate(v) if v else np.zeros(0) for k, v in parts.items()}
    # secids in alphabetical order, the rows by bond, then week (`at` searches them)
    secids = sorted(col)
    remap = np.empty(len(col), np.int32)
    for j, s in enumerate(secids):
        remap[col[s]] = j
    a["sid"] = remap[a["sid"]] if len(a["sid"]) else a["sid"].astype(np.int32)
    order = np.lexsort((a["t"], a["sid"]))
    a = {k: v[order] for k, v in a.items()}
    m = Market(dates=days, secids=secids, names=names, boards=sorted(bcol, key=bcol.get), units=sorted(ucol, key=ucol.get),
               t=a["t"], sid=a["sid"], board=a["board"], unit=a["unit"], price=a["price"], accint=a["accint"],
               face=a["face"], value=a["value"], trades=a["trades"], ytm=a["ytm"], duration=a["duration"],
               mat=a["mat"], offer=a["offer"], start=np.zeros(len(days) + 1, np.int64),
               by_week=np.argsort(a["t"], kind="stable"))
    m.start[1:] = np.cumsum(np.bincount(a["t"], minlength=len(days)))
    m.curves = list(curve(days).values())
    _market = (time.time(), year_from, m)
    return m


def cross_section(m: Market, t: int) -> np.ndarray:
    """Row indices of week `t`."""
    return m.by_week[m.week(t)]
