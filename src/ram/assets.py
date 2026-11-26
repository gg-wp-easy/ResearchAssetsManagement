"""A basket: the assets on one calendar as excess-return indices (what a long financed at the carry earns).

- Weekends are dropped: a Saturday or Sunday move (crypto, MOEX weekend sessions) lands in Monday's return, as the bot
  folds weekend sessions (trade-t-bot trend.fold_weekends).
- The calendar is the union of the assets' trading days; on a day an asset does not trade its return is NaN and its
  position is simply held.
- Carry (what the long pays, annual): rub = RUONIA (8% before 2010, as the bot's research assumed), usd = 13-week
  T-bill, rub-usd = their difference (a USD/RUB forward), fixed = only the offset, none = nothing. carry_offset is added
  (the yuan's long pays RUONIA - 2.5%). Futures already hold their carry.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields
from datetime import date

import numpy as np

from . import sources
from .store import Series

RATE_BEFORE_2010 = 0.08
CARRIES = ("auto", "none", "rub", "usd", "rub-usd", "fixed")


@dataclass
class AssetSpec:
    id: str
    label: str = ""
    rub: bool = False  # convert to rubles at the Bank of Russia's rate
    carry: str = "auto"
    carry_offset: float = 0.0
    go: float = 0.10  # initial margin, share of the notional (for the margin cap)
    short_cap: float = 1.0  # the largest short, share of the full size: 1 = no limit, 0 = long only
    vol_floor: float = 0.0  # the size is never figured from a lower annual volatility
    cbr: bool = False  # halve the position the evening before a Bank of Russia rate decision
    weight: float = 0.0  # share of the capital in a portfolio with given weights (signal "weights")

    @staticmethod
    def from_dict(d: dict) -> "AssetSpec":
        names = {f.name for f in fields(AssetSpec)}
        spec = AssetSpec(**{k: v for k, v in d.items() if k in names})
        if spec.carry not in CARRIES:
            raise ValueError(f"ставка удержания {spec.carry!r}: одна из {', '.join(CARRIES)}")
        spec.short_cap = float(min(1.0, max(0.0, spec.short_cap)))
        spec.go = float(max(0.0, spec.go))
        spec.weight = float(max(0.0, spec.weight))
        return spec


@dataclass
class Basket:
    specs: list[AssetSpec]
    labels: list[str]
    names: list[str]
    dates: list[str]
    E: np.ndarray  # T x N excess-return index, ffilled over the asset's own non-trading days, NaN before it starts
    R: np.ndarray  # T x N daily excess return on the asset's trading days, NaN otherwise
    P: np.ndarray  # T x N price in the basket's currency, ffilled
    alive: np.ndarray  # T x N between the asset's first and last day
    ppy: float  # trading days a year on this calendar
    info: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.labels)

    def index_of(self, day: str) -> int:
        """The last calendar day on or before `day` (0 if before the start)."""
        import bisect
        return max(0, bisect.bisect_right(self.dates, day) - 1)


def ffill_on(src_dates: list[str], src_values: np.ndarray, days: list[str]) -> np.ndarray:
    """The last known value of the source on each of `days` (NaN before it starts)."""
    idx = np.searchsorted(np.array(src_dates), np.array(days), side="right") - 1
    out = np.where(idx >= 0, src_values[np.clip(idx, 0, None)], np.nan)
    return out.astype(float)


def despike(days: list[str], px: np.ndarray, k: float = 8.0, back: float = 0.25, span: int = 3) -> tuple[list[str], np.ndarray, int]:
    """Drop isolated bad prints: a jump of more than k robust sigmas that comes back within `span` days to within
    `back` of the jump (Yahoo's front-month futures flip between contracts around expiry)."""
    if len(px) < 50:
        return days, px, 0
    r = np.diff(np.log(px))
    sd = 1.4826 * np.median(np.abs(r - np.median(r)))
    if not sd > 0:
        return days, px, 0
    bad = np.zeros(len(px), bool)
    i = 1
    while i < len(px) - 1:
        jump = math.log(px[i] / px[i - 1])
        if abs(jump) > k * sd:
            for s in range(1, span + 1):
                if i + s >= len(px):
                    break
                net = math.log(px[i + s] / px[i - 1])
                if abs(net) < back * abs(jump):
                    bad[i:i + s] = True
                    i += s - 1
                    break
        i += 1
    keep = ~bad
    return [d for d, k_ in zip(days, keep) if k_], px[keep], int(bad.sum())


def prefetch(ids: list[str]) -> None:
    """Load the series side by side (a first MOEX load takes tens of seconds); errors surface in `build`."""
    def one(i: str) -> None:
        try:
            sources.load(i)
        except Exception:
            pass
    todo = list(dict.fromkeys(ids))
    if len(todo) > 1:
        with ThreadPoolExecutor(min(4, len(todo))) as pool:
            list(pool.map(one, todo))


def _weekdays(s: Series) -> tuple[list[str], np.ndarray]:
    keep = [i for i, d in enumerate(s.dates) if date.fromisoformat(d).weekday() < 5]
    return [s.dates[i] for i in keep], s.values[keep]


def carry_kind(spec: AssetSpec, currency: str, series: Series) -> str:
    if spec.carry != "auto":
        return spec.carry
    if series.type in ("future", "futures") or series.kind == "rate":
        return "none"
    return {"RUB": "rub", "USD": "usd"}.get(currency, "none")


def carry_rate(kind: str, days: list[str], warnings: list[str]) -> np.ndarray:
    def rub() -> np.ndarray:
        s = sources.load("cbr:RUONIA")
        r = ffill_on(s.dates, s.values, days)
        if np.isnan(r).any():
            note = f"RUONIA до {s.dates[0]} принята {RATE_BEFORE_2010:.0%} (как в исследовании бота)"
            if note not in warnings:
                warnings.append(note)
        return np.where(np.isfinite(r), r, RATE_BEFORE_2010)

    def usd() -> np.ndarray:
        s = sources.load("yahoo:^IRX")
        r = ffill_on(s.dates, s.values, days)
        return np.where(np.isfinite(r), r, float(s.values[0]))

    if kind == "rub":
        return rub()
    if kind == "usd":
        return usd()
    if kind == "rub-usd":
        return rub() - usd()
    return np.zeros(len(days))


def excess_index(days: list[str], price: np.ndarray, rate: np.ndarray) -> np.ndarray:
    """Value of a long financed at `rate` (annual, known the day before), the carry paid per calendar day."""
    ordinals = np.array([date.fromisoformat(d).toordinal() for d in days])
    r = price[1:] / price[:-1] - 1
    carry = rate[:-1] * np.diff(ordinals) / 365
    return np.r_[1.0, np.cumprod(1 + r - carry)]


def build(specs: list[AssetSpec], history_from: str | None = None, history_to: str | None = None) -> Basket:
    if not specs:
        raise ValueError("корзина пуста")
    warnings: list[str] = []
    prefetch([s.id for s in specs])
    own: list[tuple[list[str], np.ndarray, np.ndarray]] = []
    info, labels, names = [], [], []
    for spec in specs:
        s = sources.load(spec.id)
        if s.stale:
            warnings.append(f"{spec.id}: источник не ответил, взята сохранённая копия")
        days, px = _weekdays(s)
        label = spec.label or s.name
        if s.source == "Yahoo Finance" and s.type == "future":
            days, px, dropped = despike(days, px)
            warnings.append(f"{label}: ближний фьючерс Yahoo без поправки на смену контракта - гэпы ролла остаются в "
                            "доходности; надёжнее склейка FORTS (moex:cont) или фонд"
                            + (f"; убрано выбросов: {dropped}" if dropped else ""))
        currency = s.currency
        if spec.rub and currency != "RUB":
            fx = sources.load(f"cbr:{currency}")
            rate = ffill_on(fx.dates, fx.values, days)
            ok = np.isfinite(rate)
            days, px = [d for d, k in zip(days, ok) if k], px[ok] * rate[ok]
            currency = "RUB"
        keep = [i for i, d in enumerate(days) if (not history_from or d >= history_from) and (not history_to or d <= history_to)]
        days, px = [days[i] for i in keep], px[keep]
        if len(days) < 30:
            raise ValueError(f"{spec.id}: меньше 30 дней истории в выбранном периоде")
        kind = carry_kind(spec, currency, s)
        rate = carry_rate(kind, days, warnings) + (spec.carry_offset if kind != "none" else 0.0)
        if kind == "none" and spec.carry_offset:
            rate = rate + spec.carry_offset
            kind = "fixed"
        E = excess_index(days, px, rate) if s.kind != "rate" else np.cumprod(np.r_[1.0, 1 + px[:-1] / 252])
        own.append((days, E, px))
        labels.append(label)
        names.append(s.name)
        info.append({"id": spec.id, "label": label, "name": s.name, "source": s.source, "currency": currency,
                     "native_currency": s.currency, "type": s.type, "carry": kind, "carry_offset": spec.carry_offset,
                     "first": days[0], "last": days[-1], "days": len(days), "note": s.note, "stale": s.stale})
        if s.note:
            warnings.append(f"{label}: {s.note}")
    calendar = sorted(set().union(*[set(d) for d, _, _ in own]))
    T, N = len(calendar), len(own)
    pos = {d: i for i, d in enumerate(calendar)}
    E = np.full((T, N), np.nan)
    R = np.full((T, N), np.nan)
    P = np.full((T, N), np.nan)
    alive = np.zeros((T, N), bool)
    for j, (days, e, px) in enumerate(own):
        ii = np.array([pos[d] for d in days])
        E[ii, j], P[ii, j] = e, px
        R[ii[1:], j] = e[1:] / e[:-1] - 1
        alive[ii[0]:ii[-1] + 1, j] = True
        for M in (E, P):  # ffill inside the asset's life
            col = M[ii[0]:ii[-1] + 1, j]
            idx = np.where(np.isfinite(col), np.arange(len(col)), 0)
            np.maximum.accumulate(idx, out=idx)
            M[ii[0]:ii[-1] + 1, j] = col[idx]
    years = (date.fromisoformat(calendar[-1]) - date.fromisoformat(calendar[0])).days / 365.25
    ppy = (T - 1) / years if years > 0.5 else 252.0
    return Basket(specs=specs, labels=labels, names=names, dates=calendar, E=E, R=R, P=P, alive=alive, ppy=ppy,
                  info=info, warnings=warnings)


def weekly(b: Basket) -> tuple[list[str], np.ndarray]:
    """(week-ending days, W x N weekly excess returns; NaN where the asset was not alive the whole week)."""
    keys = [date.fromisoformat(d).isocalendar()[:2] for d in b.dates]
    ends, rows, start = [], [], 0
    for i in range(1, len(keys) + 1):
        if i == len(keys) or keys[i] != keys[start]:
            block = b.R[start:i]
            r = np.prod(1 + np.nan_to_num(block), axis=0) - 1
            full = b.alive[start:i].all(axis=0) & (start > 0) & b.alive[max(start - 1, 0)]
            rows.append(np.where(full, r, np.nan))
            ends.append(b.dates[i - 1])
            start = i
    return ends, np.array(rows)


def years_between(a: str, b: str) -> float:
    return max((date.fromisoformat(b) - date.fromisoformat(a)).days / 365.25, 1e-9)


def finite_mean(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else math.nan
