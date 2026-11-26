"""Price series and their disk cache (data/cache/*.json): a series is fetched again when older than max_age, and the
stale copy is used when the source does not answer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np


def data_dir() -> Path:
    env = os.environ.get("RAM_DATA")
    if env:
        return Path(env)
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").exists():
        return root / "data" / "cache"
    return Path.home() / ".cache" / "ram"


@dataclass
class Series:
    id: str
    name: str
    currency: str  # ISO code of the price; RUB for MOEX
    dates: list[str]  # ISO days, ascending
    values: np.ndarray
    source: str = ""
    type: str = ""  # equity | etf | future | index | currency | crypto | rate ...
    kind: str = "price"  # price | rate (a rate is a share per year: 0.075)
    note: str = ""
    stale: bool = field(default=False, compare=False)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "currency": self.currency, "source": self.source, "type": self.type,
                "kind": self.kind, "note": self.note, "rows": [[d, float(v)] for d, v in zip(self.dates, self.values)]}

    @staticmethod
    def from_dict(d: dict) -> "Series":
        rows = d.get("rows", [])
        return Series(id=d["id"], name=d.get("name", d["id"]), currency=d.get("currency", ""), source=d.get("source", ""),
                      type=d.get("type", ""), kind=d.get("kind", "price"), note=d.get("note", ""),
                      dates=[r[0] for r in rows], values=np.array([float(r[1]) for r in rows]))


def _path(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:80]
    digest = hashlib.sha1(key.encode()).hexdigest()[:8]
    return data_dir() / f"{safe}.{digest}.json"


_memory: dict[str, tuple[float, Series]] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def cached(key: str, fetcher: Callable[[], Series], max_age_hours: float = 12) -> Series:
    """The series for `key`: from memory or disk while fresh, else from `fetcher`; a failed fetch falls back to the stale
    copy (marked `stale`)."""
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        now = time.time()
        hit = _memory.get(key)
        if hit and now - hit[0] < max_age_hours * 3600:
            return hit[1]
        path = _path(key)
        disk = None
        if path.exists():
            try:
                blob = json.loads(path.read_text())
                disk = (float(blob["fetched"]), Series.from_dict(blob["series"]))
            except (ValueError, KeyError):
                disk = None
        if disk and now - disk[0] < max_age_hours * 3600:
            _memory[key] = disk
            return disk[1]
        try:
            series = fetcher()
        except Exception:
            if disk:
                disk[1].stale = True
                _memory[key] = (now, disk[1])
                return disk[1]
            raise
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched": now, "series": series.as_dict()}, ensure_ascii=False))
        _memory[key] = (now, series)
        return series


def cached_json(key: str, fetcher: Callable[[], object], max_age_hours: float = 24 * 7) -> object:
    """Any JSON (catalogues): the same policy as `cached`."""
    path = _path("json:" + key)
    now = time.time()
    if path.exists():
        try:
            blob = json.loads(path.read_text())
            if now - float(blob["fetched"]) < max_age_hours * 3600:
                return blob["value"]
        except (ValueError, KeyError):
            pass
    try:
        value = fetcher()
    except Exception:
        if path.exists():
            return json.loads(path.read_text())["value"]
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched": now, "value": value}, ensure_ascii=False))
    return value
