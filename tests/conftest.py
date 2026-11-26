from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from ram import sources
from ram.store import Series


def business_days(start: str, n: int) -> list[str]:
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def random_walk(n: int, drift: float, vol: float, seed: int, start: str = "2010-01-04") -> tuple[list[str], np.ndarray]:
    rng = np.random.default_rng(seed)
    r = rng.normal(drift / 252, vol / math.sqrt(252), n)
    return business_days(start, n), 100 * np.exp(np.cumsum(r))


@pytest.fixture
def fake_sources(monkeypatch):
    """sources.load on synthetic series: three trending random walks, a constant ruble rate and a T-bill."""
    n = 2600
    book = {}
    for k, (drift, vol) in enumerate([(0.10, 0.20), (-0.05, 0.15), (0.0, 0.10)]):
        days, px = random_walk(n, drift, vol, seed=k)
        book[f"test:A{k}"] = Series(id=f"test:A{k}", name=f"asset {k}", currency="RUB", dates=days, values=px, type="index")
    days = business_days("2009-01-01", n + 300)
    book["cbr:RUONIA"] = Series(id="cbr:RUONIA", name="RUONIA", currency="RUB", dates=days, values=np.full(len(days), 0.07),
                                kind="rate", type="rate")
    book["yahoo:^IRX"] = Series(id="yahoo:^IRX", name="T-bill", currency="USD", dates=days, values=np.full(len(days), 0.02),
                                kind="rate", type="index")

    def load(asset_id: str, max_age_hours: float = 12) -> Series:
        if asset_id not in book:
            raise sources.NotFound(asset_id)
        return book[asset_id]

    monkeypatch.setattr(sources, "load", load)
    return book
