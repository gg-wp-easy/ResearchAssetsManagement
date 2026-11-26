"""Events that take a security out of a portfolio: default, bankruptcy, delisting, suspension, the high-risk sector -
from the Moscow Exchange's own decisions (ISS news, `iss/sitenews`), parsed item by item; market alarms (a discrete
auction: a 20% move in five minutes); and the user's stop list.

The exchange's decisions are structured: each item names the issuer, the security, its trading code and ISIN and the
reason ("Основание принятия решения"), so a bond's redemption (benign) is told from a bankruptcy. Two levels:

- exclude: default ("в связи с допущенным ... дефолтом", the "Облигации Д" regime), bankruptcy procedures, a squeeze-out
  (требование о выкупе), delisting or suspension for a reason other than a redemption, maturity or conversion,
  inclusion in the high-risk sector (Сектор компаний
  повышенного инвестиционного риска), the stop list. The portfolio sells the security on the first trading day after
  the news and spreads its weight over the rest; it stays out EXCLUDE_DAYS unless new events come;
- warn: a lower listing level, staying listed after an uncured breach, extra trading restrictions, a discrete auction
  (down: a crash; up: often a buyout offer before a delisting) - shown, not acted on.

Issuer-wide events (default, bankruptcy, the high-risk sector, a breach) flag every security of the issuer: a default
on a bond takes the shares out too. The issuer of a code comes from ISS's securities search (emitent_title).
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from .net import fetch_json
from .store import data_dir

NEWS = "https://iss.moex.com/iss/sitenews.json?iss.meta=off&start={start}"
BODY = "https://iss.moex.com/iss/sitenews/{id}.json?iss.meta=off"
SEARCH = "https://iss.moex.com/iss/securities.json?iss.meta=off&limit=100&q={q}"
PAGE = 50
DEPTH_DAYS = 730  # how far back the first update reads the news (`ram events --since` reads further)
CHECK_EVERY = 3600  # seconds between looks at the news feed
EXCLUDE_DAYS = 730  # how long an exclude event keeps the security out
WARN_DAYS = 120  # how long a warning is shown
VERSION = 1

RELEVANT = ("Список ценных бумаг", "приостановке торгов", "уровня листинга", "условия проведения торгов",
            "условий проведения торгов", "повышенного инвес", "дискретный аукцион", "исключении ценных бумаг",
            "Об оставлении", "делистинг", "дефолт", "банкрот")
BENIGN = re.compile(r"погашени|конвертаци|аннулирован|обмен[ауе]? |размещени|реорганизац|истечени\w* срока обращения|"
                    r"снят\w+ с обслуживания|несостоявш|прекращени\w* (?:паевого|ипотечного)|блокировани", re.I)
BANKRUPT = re.compile(r"банкротств|\(наблюдение\)|конкурсн\w* производств|внешнее управление", re.I)
BUYOUT = re.compile(r"выкуп", re.I)
DEFAULT = re.compile(r"дефолт|Облигации Д\b|неисполнени\w* обязательств", re.I)
DECISION = re.compile(r"(исключить|приостановить|включить|перевести|оставить|возобновить|изменить)", re.I)
DAY = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
ISIN = re.compile(r"\b(RU[0-9A-Z]{10})\b")

KINDS = {  # kind: (title, level, scope)
    "default": ("дефолт", "exclude", "issuer"),
    "bankruptcy": ("банкротство", "exclude", "issuer"),
    "high_risk": ("сектор повышенного риска", "exclude", "issuer"),
    "delist": ("исключение из списка", "exclude", "security"),
    "suspend": ("приостановка торгов", "exclude", "security"),
    "buyout": ("принудительный выкуп", "exclude", "security"),
    "stoplist": ("стоп-лист", "exclude", "security"),
    "breach": ("нарушение требований листинга", "warn", "issuer"),
    "downgrade": ("смена уровня листинга", "warn", "security"),
    "restrict": ("ограничение торгов", "warn", "security"),
    "crash": ("обвал цены", "warn", "security"),
    "jump": ("резкий рост цены", "warn", "security"),
    "not_traded": ("не торгуется", "exclude", "security"),
}


@dataclass
class Event:
    id: int  # the news id (0: the stop list)
    date: str  # published
    kind: str
    level: str
    scope: str
    title: str
    issuer: str = ""
    issuer_key: str = ""
    security: str = ""
    codes: list[str] = field(default_factory=list)
    reason: str = ""
    effective: str = ""  # the day the decision takes effect, if it says so
    detail: str = ""

    @property
    def url(self) -> str:
        return f"https://www.moex.com/n{self.id}" if self.id > 0 else ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["url"] = self.url
        d["kind_title"] = KINDS[self.kind][0]
        return d


# ---------------------------------------------------------------------------- names


FORMS = re.compile(r"международная компания|(?:публичное|непубличное|закрытое|открытое)?\s*акционерное общество|"
                   r"общество с ограниченной ответственностью|\b(?:мкпао|пао|нао|зао|оао|ао|ооо)\b")


def issuer_key(name: str) -> str:
    """'Публичное акционерное общество "Группа ЛСР"' -> 'группа лср': the legal form and the quotes dropped."""
    s = (name or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'“”„]", " ", s)
    s = FORMS.sub(" ", s)
    s = re.sub(r"[^\w\s\-]", " ", s)
    return " ".join(s.split())


def core_name(name: str) -> str:
    """The last quoted part of an issuer's name ('Нефтяная компания "Роснефть"' -> 'Роснефть'), or the key."""
    parts = [p.strip() for p in re.findall(r"[\"«“]([^\"«»“”]+)", name or "") if p.strip()]
    return parts[-1] if parts else issuer_key(name)


def _day(text: str) -> str:
    m = DAY.search(text or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------- parsing


def parse(nid: int, title: str, published: str, body: str) -> list[Event]:
    """The events of one news item (none for a benign one)."""
    title, day = _clean(title), published[:10]
    out: list[Event] = []

    def add(kind: str, **kw) -> None:
        _, level, scope = KINDS[kind]
        e = Event(id=nid, date=day, kind=kind, level=level, scope=scope, title=title, **kw)
        e.issuer_key = issuer_key(e.issuer)
        out.append(e)

    if "дискретный аукцион" in title:
        m = re.search(r"бумагам\s+(\S+)", title)
        dev = re.search(r"Отклонение\s*[–—-]\s*([\d.,]+)\s*%", body)
        up = "повышение" in body
        name = re.search(rf"{re.escape(m.group(1))}\s+(.+?)\s+По состоянию", body) if m else None
        if m:
            add("jump" if up else "crash", codes=[m.group(1)], issuer=name.group(1) if name else "",
                detail=(("+" if up else "−") + dev.group(1).replace(".", ",") + "% за 5 минут") if dev else "",
                reason="дискретный аукцион: цена ушла на 20% и больше за 5 минут")
        return out

    if "условия проведения торгов" in title or "условий проведения торгов" in title:
        codes = sorted(set(ISIN.findall(body)))
        tickers = re.findall(r"RU[0-9A-Z]{10}\s+([A-Z]{3,6}P?)\b", body)
        m = re.search(r"облигациями\s+(.+?)\s+с\s+\d", title) or re.search(r"допущенным\s+(.+?)\s+дефолтом", body)
        issuer = m.group(1) if m else ""
        if DEFAULT.search(body):
            add("default", issuer=issuer, codes=codes, reason="дефолт: торги в режиме «Облигации Д»")
        elif BANKRUPT.search(body):
            add("bankruptcy", issuer=issuer, codes=codes, reason="процедура банкротства")
        elif "предстоящим исключением из Списка" in body:
            r = re.search(r"на основании (.{0,160}?)(?:,|\s+установлено)", body)  # noqa: E501
            add("delist", issuer=issuer, codes=codes, reason=r.group(1) if r else "предстоящее исключение из Списка")
        elif "для отдельных акций" in title and tickers:
            m2 = re.search(r"\d{4} года (не допускается[^.]{0,120})", body)
            add("restrict", issuer=_issuer_in_table(body), codes=sorted(set(codes + tickers)),
                reason=m2.group(1) if m2 else "дополнительные ограничения торгов")
        return out

    if "Наименование эмитента" not in body:
        return out
    starts = [m.start() for m in re.finditer(r"Наименование эмитента/организации", body)]
    for k, a in enumerate(starts):
        item = body[a:starts[k + 1] if k + 1 < len(starts) else len(body)]
        item = re.split(r"Контактная информация|В торговый день, следующий", item)[0]
        if "Основание принятия решения" not in item:
            continue  # ISS cuts long news at ~5000 characters: the last item comes without its reason
        issuer = re.search(r"организации\s*(.*?)\s*Наименование ценной бумаги", item)
        sec = re.search(r"Наименование ценной бумаги\s*(.*?)\s*(?:Идентификационный|Регистрационный номер|Торговый код|ISIN)", item)
        code = re.search(r"Торговый код\s*([A-Za-z0-9\-.]+)", item)
        isin = re.search(r"ISIN код\s*([A-Z0-9]{12})", item)
        reason = re.search(r"Основание принятия решения\s*(.*)", item)
        reason_text = re.split(r"\s+\d+\s*\.\s+(?=[А-ЯЁA-Z])", reason.group(1))[0] if reason else ""
        reason_text = re.sub(r"\s+\d+\s*\.(\s*\d+\s*\.)?\s*$", "", reason_text).strip()[:300]
        decision = None
        for d in DECISION.finditer(body[:a]):
            decision = d
        verb = decision.group(1).lower() if decision else ""
        effective = _day(body[decision.end():decision.end() + 60]) if decision else ""
        kw = dict(issuer=issuer.group(1).strip() if issuer else "", security=sec.group(1).strip() if sec else "",
                  codes=sorted({c for c in (code.group(1) if code else "", isin.group(1) if isin else "") if c}),
                  reason=reason_text, effective=effective)
        if "повышенного инвестиционного риска" in title and "Об исключении" not in title:
            add("high_risk", **kw)
        elif "уровня листинга" in title:
            add("downgrade", **kw)
        elif "Об оставлении" in title:
            if "нарушени" in reason_text:
                add("breach", **kw)
        elif "из Сектора" in title:
            if BANKRUPT.search(reason_text):
                add("bankruptcy", **kw)
            elif DEFAULT.search(reason_text):
                add("default", **kw)
        elif verb in ("исключить", "приостановить"):
            if BANKRUPT.search(reason_text):
                add("bankruptcy", **kw)
            elif DEFAULT.search(reason_text):
                add("default", **kw)
            elif BUYOUT.search(reason_text):
                add("buyout", **kw)
            elif not BENIGN.search(reason_text):
                add("delist" if verb == "исключить" else "suspend", **kw)
    return _merge(out)


def _merge(evs: list[Event]) -> list[Event]:
    """One event per kind and issuer of a news item: a decision on ten bonds of one issuer is one line."""
    out: dict[tuple, Event] = {}
    for e in evs:
        k = (e.kind, e.issuer_key or e.issuer)
        if k in out:
            out[k].codes = sorted(set(out[k].codes) | set(e.codes))
            if not out[k].reason:
                out[k].reason = e.reason
        else:
            out[k] = e
    return list(out.values())


def _issuer_in_table(body: str) -> str:
    m = re.search(r"(ПАО|АО|ООО|МКПАО)\s+\"([^\"]+)\"\s+RU", body)
    return f'{m.group(1)} "{m.group(2)}"' if m else ""


# ---------------------------------------------------------------------------- the news cache


def _path() -> Path:
    return data_dir() / f"moex-news-v{VERSION}.json"


def _load() -> dict:
    p = _path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            pass
    return {"titles": {}, "bodies": {}, "checked": 0.0}


def _page(i: int) -> list[list]:
    return fetch_json(NEWS.format(start=i * PAGE))["sitenews"]["data"]


def _body(nid: int) -> str:
    d = fetch_json(BODY.format(id=nid))["content"]
    row = dict(zip(d["columns"], d["data"][0])) if d["data"] else {}
    return _clean(row.get("body", ""))[:30000]


def update(since: str | None = None, force: bool = False, progress=None) -> dict:
    """Read the news feed down to `since` (default: DEPTH_DAYS back) and the bodies of the relevant ones; a second
    call within CHECK_EVERY seconds reads nothing. Returns the cache."""
    blob = _load()
    titles: dict[str, list] = blob["titles"]
    since = since or (date.today() - timedelta(days=DEPTH_DAYS)).isoformat()
    oldest = min((v[1][:10] for v in titles.values()), default="9999")
    fresh = time.time() - blob.get("checked", 0) < CHECK_EVERY
    if fresh and not force and oldest <= since:
        return blob
    with ThreadPoolExecutor(6) as pool:
        # 1) the new end of the feed down to the cached block; 2) past the cache down to `since`
        mode, i = ("new" if titles else "deep"), 0
        while i < 3000:
            rows = [r for p in pool.map(_page, range(i, i + 6)) for r in p]
            i += 6
            if not rows:
                break
            seen = any(str(r[0]) in titles for r in rows)
            for r in rows:
                titles[str(r[0])] = [r[2], r[3]]
            last = min(r[3][:10] for r in rows)
            if progress:
                progress(f"новости до {last}: {len(titles)}")
            if mode == "new":
                if seen:
                    if oldest <= since:
                        break
                    mode, i = "deep", max(i, len(titles) // PAGE - 6)
            elif last < since:
                break
        want = [int(k) for k, v in titles.items() if any(x in html.unescape(v[0]) for x in RELEVANT)
                and str(k) not in blob["bodies"] and not html.unescape(v[0]).startswith("О регистрации")]
        for nid, text in zip(want, pool.map(_body, want)):
            blob["bodies"][str(nid)] = text
    blob["checked"] = time.time()
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(blob, ensure_ascii=False))
    _parsed.clear()
    return blob


_parsed: dict[int, list[Event]] = {}


def all_events(refresh: bool = True) -> tuple[list[Event], dict]:
    """Every event of the cached news and the stop list, newest first; (events, coverage)."""
    try:
        blob = update() if refresh else _load()
    except Exception:  # the exchange did not answer: what the cache has
        blob = _load()
    key = len(blob["bodies"]) * 100003 + len(blob["titles"])
    if key not in _parsed:
        _parsed.clear()
        evs: list[Event] = []
        for nid, body in blob["bodies"].items():
            t = blob["titles"].get(nid)
            if t:
                evs.extend(parse(int(nid), t[0], t[1], body))
        _parsed[key] = evs
    evs = list(_parsed[key]) + stop_events()
    evs.sort(key=lambda e: (e.date, e.id), reverse=True)
    dates = [v[1][:10] for v in blob["titles"].values()]
    cov = {"from": min(dates) if dates else None, "to": max(dates) if dates else None, "news": len(dates),
           "read": len(blob["bodies"]), "checked": blob.get("checked", 0.0)}
    return evs, cov


# ---------------------------------------------------------------------------- issuers


def _issuers_path() -> Path:
    return data_dir() / "moex-issuers.json"


_issuers: dict | None = None
_lock = threading.Lock()


def _issuers_cache() -> dict:
    global _issuers
    if _issuers is None:
        p = _issuers_path()
        try:
            _issuers = json.loads(p.read_text()) if p.exists() else {}
        except ValueError:
            _issuers = {}
        _issuers.setdefault("codes", {})
        _issuers.setdefault("names", {})
    return _issuers


def _save_issuers() -> None:
    with _lock:
        p = _issuers_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_issuers_cache(), ensure_ascii=False))


def _search(q: str) -> list[dict]:
    r = fetch_json(SEARCH.format(q=quote(q)))["securities"]
    return [dict(zip(r["columns"], row)) for row in r["data"]]


def security(code: str, save: bool = True) -> dict:
    """{secid, isin, shortname, issuer, issuer_key, is_traded, type} of a trading code or ISIN (ISS search, cached)."""
    c = _issuers_cache()["codes"]
    if code not in c:
        try:
            rows = _search(code)
        except Exception:
            return {"secid": code, "issuer": "", "issuer_key": "", "is_traded": None}
        hit = next((r for r in rows if code in (r.get("secid"), r.get("isin"))), None)
        info = {"secid": hit["secid"], "isin": hit.get("isin") or "", "shortname": hit.get("shortname") or "",
                   "issuer": hit.get("emitent_title") or "", "issuer_key": issuer_key(hit.get("emitent_title") or ""),
                   "is_traded": hit.get("is_traded"), "type": hit.get("type") or "", "checked": time.time()} if hit else \
            {"secid": code, "isin": "", "shortname": "", "issuer": "", "issuer_key": "", "is_traded": None, "type": "",
             "checked": time.time()}
        with _lock:
            c[code] = info
        if save:
            _save_issuers()
    return c[code]


def prefetch(codes: list[str]) -> None:
    """Look the codes' issuers up side by side (ISS search), then save the cache once."""
    todo = [x for x in dict.fromkeys(codes) if x not in _issuers_cache()["codes"]]
    if todo:
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda x: security(x, save=False), todo))
        _save_issuers()


def issuer_securities(issuer: str, save: bool = True) -> list[dict]:
    """Every security of an issuer named in the news: ISS search by its quoted name, kept when the issuer matches."""
    key = issuer_key(issuer)
    n = _issuers_cache()["names"]
    if key and key not in n:
        found: list[dict] = []
        for q in dict.fromkeys([core_name(issuer), key.split()[-1] if key else ""]):
            if len(q) < 3:
                continue
            try:
                rows = _search(q)
            except Exception:
                continue
            found = [{"secid": r["secid"], "isin": r.get("isin") or "", "type": r.get("type") or "",
                      "is_traded": r.get("is_traded")} for r in rows if issuer_key(r.get("emitent_title") or "") == key]
            if found:
                break
        with _lock:
            n[key] = found
        if save:
            _save_issuers()
    return n.get(key, [])


# ---------------------------------------------------------------------------- the stop list


def _user_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "user" if (root / "pyproject.toml").exists() else Path.home() / ".config" / "ram"


def stoplist() -> list[dict]:
    p = _user_dir() / "stoplist.json"
    try:
        return json.loads(p.read_text()) if p.exists() else []
    except ValueError:
        return []


def save_stoplist(items: list[dict]) -> list[dict]:
    clean = []
    for it in items:
        code = str(it.get("code", "")).strip().upper()
        if not re.fullmatch(r"[A-Z0-9\-.]{2,20}", code):
            raise ValueError(f"код бумаги {code!r}: тикер или ISIN")
        day = str(it.get("date") or date.today().isoformat())[:10]
        date.fromisoformat(day)
        clean.append({"code": code, "reason": str(it.get("reason", ""))[:300], "date": day})
    p = _user_dir() / "stoplist.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, ensure_ascii=False, indent=1))
    return clean


def stop_events() -> list[Event]:
    return [Event(id=0, date=s["date"], kind="stoplist", level="exclude", scope="security", title="стоп-лист",
                  codes=[s["code"]], reason=s.get("reason") or "добавлено вручную") for s in stoplist()]


# ---------------------------------------------------------------------------- checks


def _alive(e: Event, today: str) -> bool:
    days = EXCLUDE_DAYS if e.level == "exclude" else WARN_DAYS
    return e.date >= (date.fromisoformat(today) - timedelta(days=days)).isoformat()


def matches(e: Event, info: dict) -> bool:
    ids = {info.get("secid"), info.get("isin")} - {"", None}
    if ids & set(e.codes):
        return True
    return e.scope == "issuer" and bool(e.issuer_key) and e.issuer_key == info.get("issuer_key")


def check(codes: list[str], events: list[Event] | None = None, today: str | None = None) -> dict[str, dict]:
    """For each code (ticker or ISIN): status exclude / warn / ok, the events behind it (newest first), the issuer."""
    today = today or date.today().isoformat()
    events = events if events is not None else all_events()[0]
    prefetch(codes)
    out = {}
    for code in codes:
        info = security(code)
        hits = [e for e in events if _alive(e, today) and matches(e, info)]
        if info.get("is_traded") == 0:
            hits.insert(0, Event(id=0, date=today, kind="not_traded", level="exclude", scope="security",
                                 title="бумага не торгуется на бирже", codes=[code], reason="по данным ISS"))
        hits.sort(key=lambda e: e.level != "exclude")  # the reason to sell first; a stable sort: each level newest first
        status = "exclude" if any(e.level == "exclude" for e in hits) else "warn" if hits else "ok"
        out[code] = {"code": code, "status": status, "issuer": info.get("issuer", ""), "name": info.get("shortname", ""),
                     "events": [e.as_dict() for e in hits]}
    return out


def exits(events: list[Event] | None = None, shares_only: bool = True) -> dict[str, list[tuple[str, str, Event]]]:
    """Point in time: code -> [(from, to, event)] - the security is out of the portfolio after `from` (the news day:
    sold on the next trading day) until `to`. Issuer-wide events reach every security of the issuer."""
    events = events if events is not None else all_events()[0]
    names = {e.issuer for e in events if e.level == "exclude" and e.scope == "issuer" and e.issuer}
    todo = [x for x in names if issuer_key(x) not in _issuers_cache()["names"]]
    if todo:
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda x: issuer_securities(x, save=False), todo))
        _save_issuers()
    out: dict[str, list[tuple[str, str, Event]]] = {}
    for e in events:
        if e.level != "exclude" or e.kind == "not_traded":
            continue
        codes = set(e.codes)
        if e.scope == "issuer" and e.issuer:
            for s in issuer_securities(e.issuer):
                if not shares_only or s.get("type") in ("common_share", "preferred_share", "depositary_receipt"):
                    codes.add(s["secid"])
        end = (date.fromisoformat(e.date) + timedelta(days=EXCLUDE_DAYS)).isoformat()
        for c in codes:
            out.setdefault(c, []).append((e.date, end, e))
    for c in out:
        out[c].sort(key=lambda x: x[0])
    return out


def excluded(spans: list[tuple[str, str, Event]] | None, day: str) -> Event | None:
    """The event keeping a security out on `day` (news strictly before it), or None."""
    for a, b, e in spans or []:
        if a < day <= b:
            return e
    return None


def feed(days: int = 90, level: str | None = None) -> dict:
    evs, cov = all_events()
    lo = (date.today() - timedelta(days=days)).isoformat()
    rows = [e.as_dict() for e in evs if e.date >= lo and (level is None or e.level == level)]
    return {"coverage": cov, "events": rows}
