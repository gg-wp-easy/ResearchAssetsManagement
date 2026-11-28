"""HTTP API of the site and the built frontend (web/dist) on the same port."""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, account, bonds, book, capital, events, factors, ml, sas, sources, watch
from .net import NotFound
from .presets import PRESETS
from .rule import CONTROLS, Params
from .scenarios import WINDOWS
from .study import clean, run_study

app = FastAPI(title="Research Assets Management", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

_results: OrderedDict[str, dict] = OrderedDict()
_lock = threading.Lock()
_factor_lock = threading.Lock()  # one panel build at a time: the first one downloads ~700 weeks of ISS


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/meta")
def meta() -> dict:
    return {"presets": PRESETS, "controls": [c.__dict__ for c in CONTROLS], "windows": WINDOWS,
            "defaults": Params().as_dict(), "carries": {"auto": "по валюте", "none": "нет (фьючерс, индекс цены)",
                                                       "rub": "RUONIA", "usd": "T-bill США", "rub-usd": "RUONIA − T-bill",
                                                       "fixed": "только поправка"}}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=60)) -> list[dict]:
    return sources.search(q)


@app.get("/api/series")
def series(id: str = Query(..., max_length=80)) -> dict:
    """Short description of one asset: name, source, first and last day (a check before adding it)."""
    try:
        s = sources.load(id)
    except NotFound as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # the source did not answer
        raise HTTPException(502, f"{id}: {e}") from e
    return {"id": s.id, "name": s.name, "currency": s.currency, "source": s.source, "type": s.type, "kind": s.kind,
            "first": s.dates[0], "last": s.dates[-1], "days": len(s.dates), "last_value": float(s.values[-1]),
            "note": s.note}


@app.post("/api/study")
def study(req: dict) -> dict:
    key = hashlib.sha1(json.dumps(req, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
    try:
        res = run_study(req)
    except NotFound as e:
        raise HTTPException(404, str(e)) from e
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e)) from e
    return _remember(key, res)


def _remember(key: str, res: dict) -> dict:
    with _lock:
        _results[key] = res
        while len(_results) > 16:
            _results.popitem(last=False)
    return res


@app.post("/api/factors")
def factor_lab(req: dict) -> dict:
    start, top, cost = _lab_params(req)
    key = "factors:" + json.dumps([start, top, cost])
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
    with _factor_lock:
        try:
            res = clean(factors.lab(start, top, cost))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return _remember(key, res)


def _lab_params(req: dict) -> tuple[str, int, float]:
    from datetime import date
    try:
        start = date.fromisoformat(str(req.get("start") or "2015-01-01")[:10]).isoformat()
        top, cost = int(req.get("top", 100)), float(req.get("cost", 0.002))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"параметры лаборатории: {e}") from e
    if not 20 <= top <= 1000 or not 0 <= cost <= 0.05:
        raise HTTPException(400, "бумаг во вселенной — от 20 до 1000, издержки — от 0 до 5% за сторону")
    return start, top, cost


@app.post("/api/ml")
def ml_lab(req: dict) -> dict:
    start, top, cost = _lab_params(req)
    key = "ml:" + json.dumps([start, top, cost])
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
    with _factor_lock:
        try:
            res = clean(ml.lab(start, top, cost))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return _remember(key, res)


@app.post("/api/book")
def book_report(req: dict) -> dict:
    """The book of sleeves (book.py): equity picks, bonds, the bot's trend and cash under a risk budget and a scenario cap."""
    key = "book:" + json.dumps(req, sort_keys=True, ensure_ascii=False)
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
    with _factor_lock:
        try:
            res = clean(book.report(req))
        except NotFound as e:
            raise HTTPException(404, str(e)) from e
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, str(e)) from e
    return _remember(key, res)


@app.post("/api/bonds")
def bonds_report(req: dict) -> dict:
    """The bond sleeve from single issues (bonds.py): OFZ ПД, ПК, ИН and corporates against the indices and SBGB."""
    tax = float(req.get("tax", bonds.TAX))
    if not 0 <= tax < 1:
        raise HTTPException(400, "налог — доля от 0 до 1")
    key = f"bonds:{tax}"
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
    with _factor_lock:
        try:
            res = clean(bonds.report(tax))
        except NotFound as e:
            raise HTTPException(404, str(e)) from e
    return _remember(key, res)


@app.get("/api/account/settings")
def account_settings_get() -> dict:
    """The account's settings and the wealth outside it (data/user/account.json, outside git)."""
    return account.load_settings().as_dict()


@app.put("/api/account/settings")
def account_settings_put(req: dict) -> dict:
    try:
        return account.save_settings(req).as_dict()
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/account")
def account_report(req: dict) -> dict:
    """The book on a real account (account.py): whole lots and contracts, fees, the tax, the plan, the wealth around it."""
    s = account.load_settings()
    key = "account:" + json.dumps({"req": req, "s": s.as_dict()}, sort_keys=True, ensure_ascii=False)
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
    with _factor_lock:
        try:
            res = clean(account.report(req))
        except NotFound as e:
            raise HTTPException(404, str(e)) from e
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, str(e)) from e
    return _remember(key, res)


@app.post("/api/capital")
def capital_report(req: dict) -> dict:
    """The whole capital (capital.py): the account's book, gold, currency and real-estate funds; plans of their shares."""
    s = account.load_settings()
    key = "capital:" + json.dumps({"req": req, "s": s.as_dict()}, sort_keys=True, ensure_ascii=False)
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
    with _factor_lock:
        try:
            res = clean(capital.report(req))
        except NotFound as e:
            raise HTTPException(404, str(e)) from e
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, str(e)) from e
    return _remember(key, res)


def _forget() -> None:
    """The stop list or the news changed: every computed study and the book's sleeves are stale."""
    with _lock:
        _results.clear()
    book._cache.clear()


@app.get("/api/events/feed")
def events_feed(days: int = Query(90, ge=1, le=1500), level: str | None = Query(None, pattern="^(exclude|warn)$")) -> dict:
    """The exchange's events (events.py) of the last `days`: defaults, bankruptcy, delisting, the high-risk sector..."""
    return clean(events.feed(days, level))


@app.post("/api/events/check")
def events_check(req: dict) -> dict:
    codes = [str(c).strip().upper() for c in req.get("codes", []) if str(c).strip()]
    if not codes or len(codes) > 300:
        raise HTTPException(400, "коды бумаг: от 1 до 300 тикеров или ISIN")
    return clean(events.check(codes))


@app.get("/api/events/portfolios")
def events_portfolios() -> dict:
    """server-analytic-system's portfolios and the book's picks against the events, the weights without the excluded."""
    with _factor_lock:
        return clean(watch.portfolios())


@app.get("/api/events/stoplist")
def stoplist_get() -> dict:
    return {"items": events.stoplist()}


@app.put("/api/events/stoplist")
def stoplist_put(req: dict) -> dict:
    try:
        items = events.save_stoplist(list(req.get("items", [])))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    _forget()
    return {"items": items}


@app.post("/api/events/update")
def events_update() -> dict:
    try:
        events.update(force=True)
    except Exception as e:  # the exchange did not answer
        raise HTTPException(502, f"лента Мосбиржи не ответила: {e}") from e
    _forget()
    return clean(events.all_events(refresh=False)[1])


@app.get("/api/sas")
def sas_status() -> dict:
    """Whether server-analytic-system's data is at hand (dividends, smart-lab reports)."""
    root = sas.sas_dir()
    divs, reps = sas.dividends(), sas.reports()
    return {"dir": str(root) if root else None, "dividends": sum(len(v) for v in divs.values()) if divs else 0,
            "dividend_tickers": len(divs or {}), "report_tickers": len(reps or {})}


def _mount_frontend() -> None:
    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if not (dist / "index.html").exists():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (dist / path).resolve()
        if path and target.is_file() and dist in target.parents:
            return FileResponse(target)
        return FileResponse(dist / "index.html")


_mount_frontend()
