"""Where the prices come from.

- Yahoo Finance (`yahoo:<symbol>`): shares, funds, futures, indices, currencies and crypto of the world; adjusted closes
  (dividends and splits) where Yahoo has them.
- MOEX ISS (`moex:<market>:<secid>`, market = shares | index | currency | futures): closes of the main boards. ISS no longer
  publishes dividends, so a share's return is the price return (a dividend yield goes into the carry, see assets.py).
- The Bank of Russia (`cbr:<ISO code>` - the official rate in rubles, from 1998; `cbr:RUONIA` - from 2010).
"""
from __future__ import annotations

import math
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from urllib.parse import quote

import numpy as np

from .net import NotFound, fetch, fetch_json
from .store import Series, cached, cached_json

ISS = "https://iss.moex.com/iss"
CBR = "https://www.cbr.ru"

# market -> (engine, ISS market, columns, boards in order of preference)
MOEX_MARKETS = {
    "shares": ("stock", "shares", "TRADEDATE,BOARDID,CLOSE",
               ["TQBR", "TQTF", "TQIF", "TQPI", "TQBS", "TQNL", "TQNE", "TQLV", "TQDE", "TQTD", "EQBR", "EQNE", "EQNL",
                "EQBS", "EQLV", "EQDE", "EQOB"]),
    "index": ("stock", "index", "TRADEDATE,BOARDID,CLOSE", ["SNDX", "RTSI"]),
    "currency": ("currency", "selt", "TRADEDATE,BOARDID,CLOSE", ["CETS"]),
    "futures": ("futures", "forts", "TRADEDATE,BOARDID,CLOSE,SETTLEPRICE", ["RFUD"]),
}
MOEX_GROUPS = {"stock_shares": "shares", "stock_dr": "shares", "stock_etf": "shares", "stock_ppif": "shares",
               "stock_index": "index", "currency_selt": "currency", "futures_forts": "futures"}
MARKET_LABEL = {"shares": "акции и фонды", "index": "индекс", "currency": "валюта", "futures": "фьючерс"}
YAHOO_CURRENCY = {"GBp": "GBP", "ZAc": "ZAR", "ILA": "ILS"}


def load(asset_id: str, max_age_hours: float = 12) -> Series:
    source, _, rest = asset_id.partition(":")
    if source == "yahoo" and rest:
        return cached(asset_id, lambda: yahoo(rest), max_age_hours)
    if source == "moex":
        market, _, secid = rest.partition(":")
        if market == "cont" and secid:
            return cached(asset_id, lambda: moex_continuous(secid), max_age_hours)
        if market in MOEX_MARKETS and secid:
            return cached(asset_id, lambda: moex(market, secid), max_age_hours)
    if source == "cbr" and rest:
        return cached(asset_id, lambda: cbr(rest.upper()), max_age_hours)
    raise NotFound(f"неизвестный код актива: {asset_id}")


# ---------------------------------------------------------------------------- Yahoo


def yahoo(symbol: str) -> Series:
    until = int(time.time()) + 86400
    j = fetch_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?period1=0&period2={until}"
                   "&interval=1d&events=div%2Csplit&includeAdjustedClose=true")
    result = (j.get("chart") or {}).get("result") or []
    if not result or not result[0].get("timestamp"):
        raise NotFound(f"Yahoo не знает {symbol}")
    r = result[0]
    meta = r.get("meta", {})
    ind = r.get("indicators", {})
    close = (ind.get("quote") or [{}])[0].get("close") or []
    adj = ((ind.get("adjclose") or [{}])[0] or {}).get("adjclose")
    use_adj = bool(adj) and any(v is not None for v in adj)
    values = adj if use_adj else close
    offset = int(meta.get("gmtoffset") or 0)
    by_day: dict[str, float] = {}
    for t, v in zip(r["timestamp"], values):
        if v is None or not v > 0:
            continue
        by_day[datetime.fromtimestamp(t + offset, tz=timezone.utc).date().isoformat()] = float(v)
    days = sorted(by_day)
    if len(days) < 2:
        raise NotFound(f"у Yahoo нет истории {symbol}")
    kind = "price"
    vals = np.array([by_day[d] for d in days])
    itype = str(meta.get("instrumentType") or "").lower()
    if symbol in ("^IRX", "^FVX", "^TNX", "^TYX"):  # yields in percent
        kind, vals = "rate", vals / 100
    cur = str(meta.get("currency") or "USD")
    return Series(id=f"yahoo:{symbol}", name=str(meta.get("longName") or meta.get("shortName") or symbol),
                  currency=YAHOO_CURRENCY.get(cur, cur.upper()), dates=days, values=vals, source="Yahoo Finance",
                  type=itype, kind=kind, note="цены с поправкой на дивиденды и сплиты" if use_adj and itype in ("equity", "etf", "mutualfund") else "")


def yahoo_search(q: str) -> list[dict]:
    j = fetch_json(f"https://query2.finance.yahoo.com/v1/finance/search?q={quote(q)}&quotesCount=12&newsCount=0"
                   "&listsCount=0&enableFuzzyQuery=false", timeout=15, tries=2)
    out = []
    for x in j.get("quotes", []):
        sym = x.get("symbol")
        if not sym or x.get("quoteType") in ("OPTION",):
            continue
        out.append({"id": f"yahoo:{sym}", "code": sym, "name": x.get("longname") or x.get("shortname") or sym,
                    "kind": x.get("typeDisp") or x.get("quoteType") or "", "exchange": x.get("exchDisp") or x.get("exchange") or "",
                    "source": "Yahoo"})
    return out


# ---------------------------------------------------------------------------- MOEX ISS


def _iss_pages(url: str, block: str = "history") -> tuple[list[str], list[list]]:
    first = fetch_json(f"{url}&start=0")
    cols, rows = first[block]["columns"], list(first[block]["data"])
    cursor = (first.get(f"{block}.cursor") or {}).get("data") or []
    if cursor:
        c = dict(zip(first[f"{block}.cursor"]["columns"], cursor[0]))
        size, total = int(c.get("PAGESIZE") or 100), int(c.get("TOTAL") or 0)
        starts = list(range(size, total, size))
        with ThreadPoolExecutor(8) as pool:
            for page in pool.map(lambda s: fetch_json(f"{url}&start={s}")[block]["data"], starts):
                rows += page
    return cols, rows


def moex_description(secid: str) -> dict[str, str]:
    j = fetch_json(f"{ISS}/securities/{quote(secid)}.json?iss.meta=off&iss.only=description", timeout=20)
    cols = j["description"]["columns"]
    name, value = cols.index("name"), cols.index("value")
    return {row[name]: row[value] for row in j["description"]["data"]}


def moex(market: str, secid: str) -> Series:
    engine, mkt, columns, boards = MOEX_MARKETS[market]
    cols, rows = _iss_pages(f"{ISS}/history/engines/{engine}/markets/{mkt}/securities/{quote(secid)}.json?iss.meta=off"
                            f"&history.columns={columns}")
    ix = {c: i for i, c in enumerate(cols)}
    rank = {b: k for k, b in enumerate(boards)}
    best: dict[str, tuple[int, float]] = {}
    for row in rows:
        day, board = row[ix["TRADEDATE"]], row[ix["BOARDID"]]
        value = row[ix["CLOSE"]]
        if (value is None or not value > 0) and "SETTLEPRICE" in ix:
            value = row[ix["SETTLEPRICE"]]
        if value is None or not value > 0:
            continue
        k = rank.get(board, len(boards))
        if market in ("index", "futures") and board not in rank:
            k = len(boards)  # still usable: indices and futures live on one board
        elif board not in rank:
            continue  # foreign-currency and negotiated boards of shares
        if day not in best or k < best[day][0]:
            best[day] = (k, float(value))
    if len(best) < 2:
        raise NotFound(f"у Мосбиржи нет истории {secid} ({MARKET_LABEL[market]})")
    days = sorted(best)
    try:
        desc = moex_description(secid)
    except Exception:
        desc = {}
    name = desc.get("NAME") or desc.get("SHORTNAME") or secid
    note = "ценовая доходность: ISS не публикует дивиденды" if market == "shares" else ""
    if market == "index" and secid.upper().endswith("TR"):
        note = "индекс полной доходности"
    return Series(id=f"moex:{market}:{secid}", name=name, currency="RUB", dates=days,
                  values=np.array([best[d][1] for d in days]), source="Мосбиржа ISS", type=market, note=note)


FORTS_NAMES = {
    "BR": "нефть Brent", "WTI": "нефть WTI", "NG": "природный газ Henry Hub", "TTF": "газ TTF", "GOLD": "золото",
    "GL": "золото в рублях", "SILV": "серебро", "PLT": "платина", "PLD": "палладий", "COPPER": "медь",
    "ALUM": "алюминий", "NICKEL": "никель", "ZINC": "цинк", "COCOA": "какао", "COFFEE": "кофе", "SUGAR": "сахар",
    "SUGR": "сахар (российский)", "WHEAT": "пшеница", "CORN": "кукуруза", "SOYBEAN": "соя", "ORANGE": "апельсиновый сок",
    "Si": "доллар/рубль", "Eu": "евро/рубль", "CNY": "юань/рубль", "ED": "евро/доллар", "UCNY": "доллар/юань",
    "RTS": "индекс РТС", "MIX": "индекс МосБиржи", "MXI": "индекс МосБиржи (мини)", "RGBI": "индекс ОФЗ",
    "RVI": "индекс волатильности RVI", "SPYF": "S&P 500", "NASD": "Nasdaq 100", "DJ30": "Dow Jones", "R2000": "Russell 2000",
    "DAX": "DAX", "NIKK": "Nikkei 225", "HANG": "Hang Seng", "STOX": "Euro Stoxx 50", "KEYRATE": "ключевая ставка",
    "RUONIA": "RUONIA", "SBRF": "Сбербанк", "GAZR": "Газпром", "LKOH": "Лукойл", "ROSN": "Роснефть", "GMKN": "Норникель",
    "VTBR": "ВТБ", "MGNT": "Магнит", "TATN": "Татнефть", "YDEX": "Яндекс", "MOEX": "Мосбиржа", "AFLT": "Аэрофлот",
    "BTC": "Bitcoin", "ETH": "Ethereum",
}


def _iss_rows(url: str, block: str) -> list[dict]:
    j = fetch_json(url)
    cols = j[block]["columns"]
    return [dict(zip(cols, r)) for r in j[block]["data"]]


def forts_assets() -> dict[str, str]:
    """Asset codes of the futures trading now on FORTS -> a sample contract name."""
    def get() -> dict:
        rows = _iss_rows(f"{ISS}/engines/futures/markets/forts/securities.json?iss.meta=off&iss.only=securities"
                         "&securities.columns=SECID,SHORTNAME,ASSETCODE,LASTTRADEDATE", "securities")
        out: dict[str, str] = {}
        for r in rows:
            code = r.get("ASSETCODE")
            if code and r.get("LASTTRADEDATE", "") < "2090":  # perpetuals are found as moex:futures
                out.setdefault(code, r.get("SHORTNAME") or code)
        return out
    return cached_json("forts_assets", get, 24)  # type: ignore[return-value]


def moex_continuous(code: str, roll_days: int = 7) -> Series:
    """Roll-adjusted continuous futures (the trade bot's futures_roll.stitch): each day the nearest contract with at
    least `roll_days` to expiry is in use, and a day's return is taken inside the contract in use the day before, so a
    switch adds no jump. Scaled to end at the last close of the contract in use."""
    from datetime import timedelta
    rows = _iss_rows(f"{ISS}/statistics/engines/futures/markets/forts/series.json?asset_code={quote(code)}"
                     "&show_expired=1&iss.meta=off", "series")
    contracts = sorted(((r["secid"], date.fromisoformat(r["expiration_date"])) for r in rows
                        if r.get("expiration_date") and r["expiration_date"] < "2090"), key=lambda c: c[1])
    if not contracts:
        raise NotFound(f"на FORTS нет срочных контрактов {code}")
    today = date.today()
    jobs = []
    for k, (secid, expiry) in enumerate(contracts):
        lo = (contracts[k - 1][1] if k else expiry - timedelta(days=120)) - timedelta(days=roll_days + 5)
        hi = min(expiry - timedelta(days=roll_days) + timedelta(days=7), today)
        if lo <= today:
            jobs.append((secid, expiry, lo, hi))

    def get(job):
        secid, _, lo, hi = job
        try:
            _, data = _iss_pages(f"{ISS}/history/engines/futures/markets/forts/securities/{quote(secid)}.json?iss.meta=off"
                                 f"&from={lo}&till={hi}&history.columns=TRADEDATE,CLOSE,SETTLEPRICE")
        except NotFound:
            return {}
        return {d: float(c if c and c > 0 else s) for d, c, s in data if (c and c > 0) or (s and s > 0)}

    with ThreadPoolExecutor(8) as pool:
        bars = dict(zip([j[0] for j in jobs], pool.map(get, jobs)))
    expiries = {j[0]: j[1] for j in jobs}
    days, values, last = _stitch(bars, expiries, roll_days)
    if len(days) < 30:
        raise NotFound(f"у склейки {code} меньше 30 дней истории")
    return Series(id=f"moex:cont:{code}", name=f"{FORTS_NAMES.get(code, code)}: склейка фьючерсов FORTS ({code})",
                  currency="RUB", dates=days, values=np.array(values), source="Мосбиржа ISS", type="future",
                  note=f"склейка контрактов с переходом за {roll_days} дн. до экспирации; сейчас {last}")


def _stitch(bars: dict[str, dict[str, float]], expiries: dict[str, date], roll_days: int):
    dates = sorted({d for s in bars.values() for d in s})
    prev_date = prev_choice = last = None
    used, steps = [], []
    for d in dates:
        day = date.fromisoformat(d)
        alive = [t for t in bars if d in bars[t] and (expiries[t] - day).days >= roll_days]
        choice = min(alive, key=lambda t: expiries[t]) if alive else None
        step = 0.0
        if choice is not None and prev_choice is not None:
            before, after = bars[prev_choice].get(prev_date), bars[prev_choice].get(d)
            if before and after:
                step = math.log(after / before)
        if choice is not None:
            used.append(d)
            steps.append(step)
            last = choice
        prev_date, prev_choice = d, choice
    if not used:
        return [], [], None
    levels = np.cumsum([0.0] + steps[1:])
    end = bars[last][used[-1]]
    return used, list(end * np.exp(levels - levels[-1])), last


def forts_search(q: str) -> list[dict]:
    ql = q.strip().lower()
    out = []
    for code, sample in forts_assets().items():
        name = FORTS_NAMES.get(code, "")
        if ql == code.lower() or (len(ql) >= 2 and (code.lower().startswith(ql) or ql in name.lower())):
            out.append({"id": f"moex:cont:{code}", "code": code, "name": f"{name or code}: склейка фьючерсов",
                        "kind": "фьючерс FORTS, склейка", "exchange": "Мосбиржа", "source": "Мосбиржа"})
    out.sort(key=lambda r: r["code"].lower() != ql)
    return out[:8]


def moex_search(q: str) -> list[dict]:
    j = fetch_json(f"{ISS}/securities.json?q={quote(q)}&limit=30&iss.meta=off"
                   "&securities.columns=secid,shortname,name,group,primary_boardid,is_traded", timeout=15, tries=2)
    cols = j["securities"]["columns"]
    out = []
    for row in j["securities"]["data"]:
        r = dict(zip(cols, row))
        market = MOEX_GROUPS.get(r.get("group") or "")
        if not market:
            continue
        out.append({"id": f"moex:{market}:{r['secid']}", "code": r["secid"], "name": r.get("name") or r.get("shortname"),
                    "kind": MARKET_LABEL[market] + ("" if r.get("is_traded") else ", не торгуется"),
                    "exchange": "Мосбиржа", "source": "Мосбиржа", "traded": bool(r.get("is_traded"))})
    order = {"shares": 0, "futures": 1, "currency": 2, "index": 3}
    out.sort(key=lambda r: (not r["traded"], order.get(r["id"].split(":")[1], 4)))
    return out


# ---------------------------------------------------------------------------- Bank of Russia


def cbr_codes() -> dict[str, dict]:
    """ISO code -> {id, name} of the currencies the Bank of Russia quotes."""
    def get() -> dict:
        root = ET.fromstring(fetch(f"{CBR}/scripts/XML_valFull.asp", timeout=30))
        out = {}
        for item in root.findall("Item"):
            iso = (item.findtext("ISO_Char_Code") or "").strip()
            if iso:
                out[iso] = {"id": item.get("ID"), "name": (item.findtext("Name") or "").strip(),
                            "eng": (item.findtext("EngName") or "").strip()}
        return out
    return cached_json("cbr_codes", get)  # type: ignore[return-value]


def cbr(code: str) -> Series:
    if code == "RUONIA":
        return ruonia()
    codes = cbr_codes()
    if code not in codes:
        raise NotFound(f"Банк России не устанавливает курс {code}")
    xml = fetch(f"{CBR}/scripts/XML_dynamic.asp?date_req1=01/01/1998&date_req2={date.today():%d/%m/%Y}"
                f"&VAL_NM_RQ={codes[code]['id']}", timeout=60)
    by_day = {}
    for rec in ET.fromstring(xml).findall("Record"):
        d, m, y = rec.get("Date", "").split(".")
        nominal = float(rec.findtext("Nominal") or 1)
        value = float((rec.findtext("Value") or "0").replace(",", "."))
        if value > 0:
            by_day[f"{y}-{m}-{d}"] = value / nominal
    if len(by_day) < 2:
        raise NotFound(f"нет истории курса {code}")
    days = sorted(by_day)
    return Series(id=f"cbr:{code}", name=f"{codes[code]['name']} ({code}/RUB, курс Банка России)", currency="RUB",
                  dates=days, values=np.array([by_day[d] for d in days]), source="Банк России", type="currency")


def _ruonia_year(year: int) -> list[tuple[str, float]]:
    until = min(date(year, 12, 31), date.today())
    body = ('<?xml version="1.0" encoding="utf-8"?><soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
            f'<soap12:Body><Ruonia xmlns="http://web.cbr.ru/"><fromDate>{year}-01-01</fromDate><ToDate>{until}</ToDate>'
            '</Ruonia></soap12:Body></soap12:Envelope>')
    xml = fetch(f"{CBR}/DailyInfoWebServ/DailyInfo.asmx", data=body.encode(),
                headers={"Content-Type": "application/soap+xml; charset=utf-8"}, timeout=120).decode("utf-8")
    return [(d, float(v)) for d, v in re.findall(r"<D0>(\d{4}-\d\d-\d\d)T[^<]*</D0><ruo>([\d.]+)</ruo>", xml)]


def ruonia() -> Series:
    with ThreadPoolExecutor(6) as pool:
        years = list(pool.map(_ruonia_year, range(2010, date.today().year + 1)))
    by_day = {d: v / 100 for rows in years for d, v in rows}
    days = sorted(by_day)
    return Series(id="cbr:RUONIA", name="RUONIA, ставка overnight", currency="RUB", dates=days,
                  values=np.array([by_day[d] for d in days]), source="Банк России", type="rate", kind="rate")


def cbr_search(q: str) -> list[dict]:
    ql = q.strip().lower()
    if len(ql) < 2:
        return []
    out = []
    for iso, c in cbr_codes().items():
        if ql in iso.lower() or ql in c["name"].lower() or ql in c["eng"].lower():
            out.append({"id": f"cbr:{iso}", "code": iso, "name": f"{c['name']} к рублю", "kind": "курс ЦБ",
                        "exchange": "Банк России", "source": "ЦБ"})
    return out[:6]


def search(q: str) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    with ThreadPoolExecutor(4) as pool:
        jobs = [pool.submit(f, q) for f in (cbr_search, forts_search, moex_search, yahoo_search)]
        found = []
        for job in jobs:
            try:
                found += job.result()
            except Exception:
                continue
    seen, out = set(), []
    for r in found:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    ql = q.lower()

    def rank(r: dict) -> int:  # an exact code first, then a code that starts so, then the name; sources keep their order
        code, name = r["code"].lower(), (r["name"] or "").lower()
        if code == ql:
            return 0
        if code.startswith(ql):
            return 1
        return 2 if ql in name else 3
    out.sort(key=rank)
    return out[:40]
