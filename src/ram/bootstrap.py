"""Block bootstrap of the book's daily returns: the chance of a drawdown deeper than a level within a horizon, with
and without a drawdown control (the size on each path scaled by the multiplier of the day before)."""
from __future__ import annotations

import numpy as np

from .rule import Control, multipliers


def bootstrap(x: np.ndarray, length: int, n: int, rng: np.random.Generator, block: int = 21) -> np.ndarray:
    starts = rng.integers(0, len(x) - block, size=(n, length // block + 1))
    idx = (starts[:, :, None] + np.arange(block)).reshape(n, -1)[:, :length]
    return x[idx]


def path_drawdowns(paths: np.ndarray, c: Control) -> np.ndarray:
    n, length = paths.shape
    eq, peak, worst = np.ones(n), np.ones(n), np.zeros(n)
    halt = np.zeros(n, int)
    for t in range(length):
        dd = 1 - eq / peak
        if c.kind == "stop":
            start = (halt == 0) & (dd >= c.limit)
            halt[start] = c.restart
            m = np.where(halt > 0, 0.0, 1.0)
            halt = np.maximum(halt - 1, 0)
            peak = np.where((m == 0) & (halt == 0), eq, peak)
        elif c.kind == "none":
            m = 1.0
        else:
            m = multipliers(c, dd)
        eq = eq * (1 + m * paths[:, t])
        peak = np.maximum(peak, eq)
        worst = np.maximum(worst, 1 - eq / peak)
    return worst


def drawdown_odds(x: np.ndarray, controls: list[Control], ppy: float, levels=(0.15, 0.25, 0.35), horizons=(1, 3),
                  n: int = 4000, seed: int = 7) -> list[dict]:
    """P(max drawdown > level within `horizon` years) for each control. Rolling-peak controls are applied with the
    all-time peak (the bootstrap does not keep a window)."""
    rng = np.random.default_rng(seed)
    out = []
    paths = {h: bootstrap(x, int(round(ppy * h)), n, rng) for h in horizons}
    for c in controls:
        row = {"name": c.name, "odds": {}}
        for h in horizons:
            worst = path_drawdowns(paths[h], c)
            row["odds"][str(h)] = {f"{lv:.2f}": float((worst > lv).mean()) for lv in levels}
            row.setdefault("median", {})[str(h)] = float(np.median(worst))
        out.append(row)
    return out
