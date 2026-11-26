"""The trade bot's trend rule (project-trade-t-bot, trend.py and research/stress_scenarios.py) on any basket.

Each day i, after the close, for each asset:
  sigma^2 = max(EWMA_60(r^2), EWMA_fast(r^2))          (the fast window protects from sudden moves; 0 = off)
  size    = risk / (sigma * sqrt(ppy))                   (a full position: annual vol = risk of the capital)
  z_L     = ln(E_i / E_{i-L}) / (sigma * sqrt(L))        (trend strength net of carry; several windows are averaged)
  w       = clip(mean_L clip(z_L, -1, 1), -short_cap, 1) * size * cbr * m
and the position moves to w when it is a quarter of the full size away or points the other way (the "band"). m is the
drawdown control's multiplier. The positions earn day i+1's return; a change costs `cost` per unit of notional. The
margin cap scales all positions down when sum |w| * GO exceeds the cap.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import lfilter

from .assets import Basket

# Bank of Russia board meetings on the key rate (cbr.ru/dkp/cal_mp, read 2026-11-06), the extraordinary 2022-02-28 included.
CBR_MEETINGS = frozenset({
    "2021-02-12", "2021-03-19", "2021-04-23", "2021-06-11", "2021-07-23", "2021-09-10", "2021-10-22", "2021-12-17",
    "2022-02-11", "2022-02-28", "2022-03-18", "2022-04-08", "2022-04-29", "2022-05-26", "2022-06-10", "2022-07-22",
    "2022-09-16", "2022-10-28", "2022-12-16", "2023-02-10", "2023-03-17", "2023-04-28", "2023-06-09", "2023-07-21",
    "2023-08-15", "2023-09-15", "2023-10-27", "2023-12-15", "2024-02-16", "2024-03-22", "2024-04-26", "2024-06-07",
    "2024-07-26", "2024-09-13", "2024-10-25", "2024-12-20", "2025-02-14", "2025-03-21", "2025-04-25", "2025-06-06",
    "2025-07-25", "2025-09-12", "2025-10-24", "2025-12-19", "2026-02-13", "2026-03-20", "2026-04-24", "2026-06-19",
    "2026-07-24", "2026-09-11", "2026-10-23", "2026-12-18", "2027-02-12", "2027-03-19", "2027-04-30", "2027-06-11",
    "2027-07-30", "2027-09-10", "2027-10-22", "2027-12-17",
})


@dataclass(frozen=True)
class Params:
    risk: float = 0.10  # per asset: the annual volatility of a full position, share of the capital
    lookbacks: tuple[int, ...] = (20,)
    slow: int = 60
    fast: int = 20  # 0: no fast window
    cost: float = 0.0006
    band: float = 0.25  # the position moves when the target is this share of the full size away
    margin_cap: float = 0.5  # sum |w| * GO <= cap (0: no cap)
    cbr_scale: float = 0.5  # the size of the flagged assets the evening before a rate decision
    signal: str = "trend"  # trend | hold (always long a full position: the volatility-targeted holder)

    @staticmethod
    def from_dict(d: dict) -> "Params":
        known = {k: v for k, v in d.items() if k in Params.__dataclass_fields__}
        if "lookbacks" in known:
            known["lookbacks"] = tuple(sorted({int(x) for x in known["lookbacks"]})) or (20,)
        p = Params(**known)
        if not 0 < p.risk <= 2:
            raise ValueError("риск на актив - от 0 до 200%")
        if any(L < 2 or L > 500 for L in p.lookbacks):
            raise ValueError("окно тренда - от 2 до 500 дней")
        return p

    def as_dict(self) -> dict:
        d = asdict(self)
        d["lookbacks"] = list(self.lookbacks)
        return d


@dataclass(frozen=True)
class Control:
    name: str
    kind: str = "none"  # none | stop | steps | linear | gz
    limit: float = 0.25  # the drawdown at which the size reaches its floor (stop: everything is closed)
    floor: float = 0.25  # the smallest multiplier while trading
    rolling: int = 0  # the peak of the last N days (0: all time)
    restart: int = 21  # stop: trading days flat, then the book starts again from where it is
    start: float = 0.0  # linear: no cut until the drawdown reaches this

    @staticmethod
    def from_dict(d: dict) -> "Control":
        known = {k: v for k, v in d.items() if k in Control.__dataclass_fields__}
        c = Control(**known)
        if c.kind not in ("none", "stop", "steps", "linear", "gz"):
            raise ValueError(f"контроль просадки {c.kind!r} неизвестен")
        if c.kind in ("linear", "gz", "stop") and not 0 < c.limit < 1:
            raise ValueError("предел просадки - от 0 до 100%")
        if c.kind == "linear" and c.start >= c.limit:
            raise ValueError("начало контроля должно быть меньше предела")
        return c


CONTROLS = [
    Control("без контроля"),
    Control("стоп 25%, месяц пауза (бот)", "stop"),
    Control("ступени 10/15/20% → 0,75/0,5/0,25", "steps"),
    Control("линейно 1 − DD/25%, пол 0,25", "linear"),
    Control("Гроссман–Чжоу, пол 0,25", "gz"),
    Control("линейно, пик за год", "linear", rolling=252),
    Control("линейно 1 − DD/40%, пол 0,5", "linear", limit=0.40, floor=0.5),
    Control("с 10%: линейно до 35%, пол 0,25", "linear", start=0.10, limit=0.35),
    Control("с 10%: линейно до 35%, пик за год", "linear", start=0.10, limit=0.35, rolling=252),
]


def multiplier(c: Control, dd: float) -> float:
    if c.kind == "steps":
        return 0.25 if dd >= 0.20 else 0.5 if dd >= 0.15 else 0.75 if dd >= 0.10 else 1.0
    if c.kind == "linear":
        return 1.0 if dd <= c.start else max(c.floor, 1 - (dd - c.start) / (c.limit - c.start))
    if c.kind == "gz":  # exposure in proportion to the cushion W - (1 - limit) x peak
        return max(c.floor, (c.limit - dd) / (c.limit * (1 - dd))) if dd < c.limit else c.floor
    if c.kind == "stop":
        return 1.0 if dd < c.limit else 0.0
    return 1.0


def multipliers(c: Control, dd: np.ndarray) -> np.ndarray:
    """`multiplier` on an array (the stop without its pause)."""
    if c.kind == "steps":
        return np.select([dd >= 0.20, dd >= 0.15, dd >= 0.10], [0.25, 0.5, 0.75], 1.0)
    if c.kind == "linear":
        return np.where(dd <= c.start, 1.0, np.maximum(c.floor, 1 - (dd - c.start) / (c.limit - c.start)))
    if c.kind == "gz":
        safe = np.minimum(dd, c.limit)
        return np.where(dd < c.limit, np.maximum(c.floor, (c.limit - safe) / (c.limit * (1 - safe))), c.floor)
    if c.kind == "stop":
        return np.where(dd < c.limit, 1.0, 0.0)
    return np.ones_like(dd)


# ---------------------------------------------------------------------------- the signal (path-independent)


def ewma_var(R: np.ndarray, span: int) -> np.ndarray:
    """EWMA of r^2 on each asset's trading days (the first value: the first r^2), held over the other days."""
    a = 2 / (span + 1)
    out = np.full(R.shape, np.nan)
    for j in range(R.shape[1]):
        idx = np.flatnonzero(np.isfinite(R[:, j]))
        if not len(idx):
            continue
        x = R[idx, j] ** 2
        y, _ = lfilter([a], [1, -(1 - a)], x, zi=[(1 - a) * x[0]])
        col = np.full(R.shape[0], np.nan)
        col[idx] = y
        fill = np.where(np.isfinite(col), np.arange(len(col)), 0)
        np.maximum.accumulate(fill, out=fill)
        col = col[fill]
        col[: idx[0]] = np.nan
        out[:, j] = col
    return out


@dataclass
class Signal:
    ok: np.ndarray  # T x N the rule can decide this day
    size: np.ndarray  # T x N full position (notional, share of capital)
    strength: np.ndarray  # T x N mean clip(z) before the short cap
    target: np.ndarray  # T x N clip(strength, -cap, 1) * size * cbr scale
    scale: np.ndarray  # T x N the rate-decision cut
    vol: np.ndarray  # T x N annual volatility the size is figured from


def signal(b: Basket, p: Params) -> Signal:
    R, E = b.R, b.E
    T, N = R.shape
    var = ewma_var(R, p.slow)
    if p.fast:
        var = np.fmax(var, ewma_var(R, p.fast))
    floors = np.array([s.vol_floor for s in b.specs])
    var = np.fmax(var, (floors ** 2 / b.ppy)[None, :])
    count = np.cumsum(np.isfinite(R), axis=0)
    live = np.isfinite(R) & b.alive
    sd = np.sqrt(var)
    with np.errstate(divide="ignore", invalid="ignore"):
        size = p.risk / (sd * math.sqrt(b.ppy))
        zs = []
        ok = live & (count >= max(61, p.slow + 1)) & np.isfinite(E) & (var > 0)
        for L in p.lookbacks:
            past = np.full_like(E, np.nan)
            past[L:] = E[:-L]
            z = np.log(E / past) / (sd * math.sqrt(L))
            ok &= np.isfinite(z)
            zs.append(np.clip(z, -1, 1))
        strength = np.mean(zs, axis=0) if p.signal == "trend" else np.ones((T, N))
    caps = np.array([s.short_cap for s in b.specs])
    scale = np.ones((T, N))
    flagged = np.array([s.cbr for s in b.specs])
    if p.cbr_scale < 1 and flagged.any():
        eve = np.array([d in CBR_MEETINGS for d in b.dates[1:]] + [False])
        scale[np.ix_(eve, flagged)] = p.cbr_scale
    target = np.clip(strength, -caps[None, :], 1) * size * scale
    target = np.where(ok, target, 0.0)
    return Signal(ok=ok, size=np.where(ok, size, 0.0), strength=np.where(ok, strength, np.nan), target=target,
                  scale=scale, vol=sd * math.sqrt(b.ppy))


# ---------------------------------------------------------------------------- the book


@dataclass
class Run:
    x: np.ndarray  # T daily return of the book (share of capital)
    pnl: np.ndarray  # T x N each asset's share of it, costs included
    pos: np.ndarray  # T x N notional held into each day
    m: np.ndarray  # T the drawdown multiplier of each day's decision
    costs: np.ndarray  # T costs paid


def simulate(b: Basket, p: Params, control: Control = CONTROLS[0], sig: Signal | None = None,
             margin: bool = True) -> Run:
    sig = sig or signal(b, p)
    T, N = b.R.shape
    Rz = np.nan_to_num(b.R)
    go = np.array([s.go for s in b.specs])
    cap = p.margin_cap if margin else 0.0
    pos = np.zeros(N)
    out, costs, mult = np.zeros(T), np.zeros(T), np.ones(T)
    pnl, held = np.zeros((T, N)), np.zeros((T, N))
    eq, peak, halt = 1.0, 1.0, 0
    window: list[float] = []
    stop = control.kind == "stop"
    for i in range(1, T - 1):
        eq *= 1 + out[i]
        if control.rolling:
            window.append(eq)
            if len(window) > control.rolling:
                window.pop(0)
            peak = max(window)
        else:
            peak = max(peak, eq)
        dd = 1 - eq / peak
        if stop:
            m = 1.0
            if halt == 0 and dd >= control.limit:
                halt = control.restart
            if halt:
                halt -= 1
                m = 0.0
                if halt == 0:
                    peak = eq  # started again by hand: the new peak is today's capital
                    window = [eq] if control.rolling else window
        else:
            m = multiplier(control, dd)
        mult[i] = m
        alive = b.alive[i + 1]
        if m == 0:
            want = np.zeros(N)
        else:
            w = sig.target[i] * m
            moved = (np.abs(w - pos) > p.band * sig.size[i]) | (np.sign(w) != np.sign(pos)) | (sig.scale[i] < 1)
            want = np.where(sig.ok[i] & moved, w, pos)
        want = np.where(alive, want, 0.0)  # the asset's history has ended: closed
        if cap > 0:
            used = float(np.abs(want) @ go)
            if used > cap:
                want = want * (cap / used)
        c = p.cost * np.abs(want - pos)
        pnl[i + 1] = want * Rz[i + 1] - c
        out[i + 1] = pnl[i + 1].sum()
        costs[i + 1] = c.sum()
        held[i + 1] = want
        pos = want
    return Run(x=out, pnl=pnl, pos=held, m=mult, costs=costs)


def independent(b: Basket, p: Params, sig: Signal | None = None) -> np.ndarray:
    """T x N: each asset traded alone by the rule (no margin cap, no control): one pass for all of them."""
    return simulate(b, p, CONTROLS[0], sig, margin=False).pnl


def full_size_today(b: Basket, p: Params) -> tuple[np.ndarray, np.ndarray]:
    """(notional of a full position, share of capital; daily sigma) from the volatility at the end of the data."""
    sig = []
    for j in range(b.n):
        r = b.R[:, j]
        r = r[np.isfinite(r)][-260:]
        if len(r) < 25:
            sig.append(math.nan)
            continue
        v60 = vf = float(np.mean(r[:20] ** 2))
        for x in r[20:]:
            v60 += 2 / (p.slow + 1) * (x * x - v60)
            if p.fast:
                vf += 2 / (p.fast + 1) * (x * x - vf)
        v = max(v60, vf) if p.fast else v60
        v = max(v, b.specs[j].vol_floor ** 2 / b.ppy)
        sig.append(math.sqrt(v))
    s = np.array(sig)
    return p.risk / (s * math.sqrt(b.ppy)), s


def weights_today(b: Basket, p: Params, s: np.ndarray) -> np.ndarray:
    """The rule's strength at the end of the data, short cap applied (hold: 1)."""
    out = []
    for j in range(b.n):
        col = b.E[:, j]
        last = np.flatnonzero(np.isfinite(col))
        if p.signal == "hold":
            out.append(1.0)
            continue
        zs = []
        for L in p.lookbacks:
            if len(last) <= L or not np.isfinite(s[j]):
                continue
            i = last[-1]
            if not np.isfinite(col[i - L]):
                continue
            zs.append(max(-1.0, min(1.0, math.log(col[i] / col[i - L]) / (s[j] * math.sqrt(L)))))
        w = float(np.mean(zs)) if zs else 0.0
        out.append(max(-b.specs[j].short_cap, min(1.0, w)))
    return np.array(out)


def capped(notional: np.ndarray, go: np.ndarray, cap: float) -> np.ndarray:
    used = float(np.abs(np.nan_to_num(notional)) @ go)
    return notional * (cap / used) if cap > 0 and used > cap else notional
