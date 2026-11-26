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

from . import __version__, factors, ml, sas, sources
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
