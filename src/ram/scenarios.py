"""Crisis windows (what the book and each asset did) and scenarios applied to today's positions.

A black swan is not forecast: the book is sized so that no scenario on the list kills it, and the plan says in advance
what to do. A scenario is a joint move of the assets with no way out (the exchange is closed or the price gaps):
  dV = sum_i w_i N_i r_i  (the rule's positions),   dV_worst = -sum_i N_i |r_i|  (every position on the wrong side).
For a real book the loss is also shown against the money on the broker account, which holds `money_share` of it.
"""
from __future__ import annotations

import math

import numpy as np

from .assets import Basket

# (label, first day, last day, region); the window's moves are from the close of the first day to the close of the last.
WINDOWS = [
    ("1998-08: дефолт России, LTCM", "1998-08-14", "1998-10-08", "ru"),
    ("2000-03..2001-04: пузырь доткомов", "2000-03-24", "2001-04-04", "world"),
    ("2001-09-11: теракты в США", "2001-09-10", "2001-09-21", "world"),
    ("2008-09..10: Lehman, биржа закрывалась", "2008-09-12", "2008-10-31", "both"),
    ("2008-11..2009-02: плавная девальвация", "2008-10-31", "2009-02-20", "ru"),
    ("2010-05-06: флэш-крэш", "2010-05-05", "2010-05-07", "world"),
    ("2011-08: рейтинг США понижен", "2011-07-22", "2011-08-10", "world"),
    ("2014-12-15..17: чёрный вторник, ставка 17%", "2014-12-12", "2014-12-17", "ru"),
    ("2014-12: весь месяц", "2014-11-28", "2014-12-31", "ru"),
    ("2015-01-15: франк отвязан от евро", "2015-01-14", "2015-01-16", "world"),
    ("2015-08-24: девальвация юаня", "2015-08-18", "2015-08-25", "world"),
    ("2016-01: нефть $27", "2015-12-30", "2016-01-21", "both"),
    ("2018-02-05: Volmageddon", "2018-02-01", "2018-02-09", "world"),
    ("2018-04-09: санкции (Русал)", "2018-04-06", "2018-04-11", "ru"),
    ("2018-10..12: распродажа конца года", "2018-10-03", "2018-12-24", "world"),
    ("2020-02..03: ковид и нефть", "2020-02-19", "2020-03-23", "both"),
    ("2022-01..10: инфляция и ставки ФРС", "2022-01-03", "2022-10-12", "world"),
    ("2022-02-24: война", "2022-02-18", "2022-02-25", "ru"),
    ("2022-02..03: биржа закрыта, открытие", "2022-02-25", "2022-03-25", "ru"),
    ("2022-04..06: укрепление рубля", "2022-04-01", "2022-06-30", "ru"),
    ("2023-03: банки США (SVB)", "2023-03-08", "2023-03-17", "world"),
    ("2023-08-14: рубль 100, ставка +3,5", "2023-07-31", "2023-08-16", "ru"),
    ("2024-06-12: санкции на биржу", "2024-06-11", "2024-06-21", "ru"),
    ("2024-08-05: разворот иенового керри", "2024-07-31", "2024-08-05", "world"),
    ("2024-11-20..27: рубль 114", "2024-11-19", "2024-11-28", "ru"),
    ("2024-12-20: ставку не подняли", "2024-12-19", "2024-12-20", "ru"),
    ("2025-02-12: надежды на мир", "2025-02-11", "2025-02-14", "ru"),
    ("2025-04-02..08: пошлины США", "2025-04-02", "2025-04-08", "world"),
]
NO_EXIT = ("закрыта",)  # windows taken whole in the scenarios: there was no way out

BOT_HYPOTHETICAL = [  # the trade bot's main book: yuan, gold in rubles, the MOEX index, the OFZ index
    ("дефолт как в 1998 (месяц без выхода)", [1.50, 1.50, -0.60, -0.40]),
    ("санкции и девальвация, биржа закрыта 2 недели", [0.35, 0.30, -0.40, -0.15]),
    ("глобальный обвал, нефть −50%", [0.15, 0.12, -0.20, -0.06]),
    ("внеплановая ставка +5 п.п.", [-0.04, -0.03, -0.10, -0.08]),
    ("резкое укрепление рубля", [-0.20, -0.20, 0.05, 0.05]),
    ("мир и снятие санкций", [-0.12, -0.12, 0.25, 0.08]),
    ("золото −15% за день", [0.01, -0.14, 0.0, 0.0]),
]


def window_moves(b: Basket, a: str, z: str) -> np.ndarray:
    i, k = b.index_of(a), b.index_of(z)
    with np.errstate(invalid="ignore", divide="ignore"):
        return b.E[k] / b.E[i] - 1


def crisis_table(b: Basket, x: np.ndarray, pos: np.ndarray, start: int, windows=WINDOWS) -> list[dict]:
    out = []
    for label, a, z, region in windows:
        if z < b.dates[0] or a > b.dates[-1]:
            continue
        i, k = b.index_of(a), b.index_of(z)
        if k <= i:
            continue
        traded = i >= start
        moves = window_moves(b, a, z)
        book = float(np.prod(1 + x[i + 1:k + 1]) - 1) if traded else None
        worst = float(x[i + 1:k + 1].min()) if traded else None
        out.append({"label": label, "from": b.dates[i], "to": b.dates[k], "region": region, "traded": traded,
                    "book": book, "worst_day": worst,
                    "positions": [round(float(v), 4) for v in pos[i + 1]] if traded else None,
                    "moves": [None if not math.isfinite(v) else round(float(v), 5) for v in moves]})
    return out


def scenario_moves(b: Basket, windows=WINDOWS) -> list[dict]:
    """Historical joint moves: short windows whole; in longer ones every 5-day move (the worst is taken against the
    positions: over a longer span the rule turns its positions)."""
    out = []
    for label, a, z, region in windows:
        if z < b.dates[0] or a > b.dates[-1]:
            continue
        i, k = b.index_of(a), b.index_of(z)
        if k <= i:
            continue
        if any(t in label for t in NO_EXIT) or k - i <= 5:
            vecs = [window_moves(b, a, z)]
            name = label
        else:
            with np.errstate(invalid="ignore", divide="ignore"):
                vecs = [b.E[t + 5] / b.E[t] - 1 for t in range(i, k - 4)]
            name = label + " (худшие 5 дн.)"
        clean = [[None if not math.isfinite(v) else round(float(v), 5) for v in vec] for vec in vecs]
        if any(any(v is not None for v in vec) for vec in clean):
            out.append({"label": name, "region": region, "moves": clean})
    return out


def default_hypothetical(b: Basket, sigma: np.ndarray) -> list[dict]:
    if [s.id for s in b.specs] == ["cbr:CNY", "yahoo:GLD", "moex:index:MCFTR", "moex:index:RGBITR"]:
        return [{"label": label, "moves": moves} for label, moves in BOT_HYPOTHETICAL]
    n = b.n
    out = [
        {"label": "всё −20% за день (обвал без выхода)", "moves": [-0.20] * n},
        {"label": "всё +20% за день (короткие против)", "moves": [0.20] * n},
        {"label": "всё −40%: биржа закрыта месяц", "moves": [-0.40] * n},
    ]
    if np.isfinite(sigma).all():
        out.append({"label": "6 дневных сигм вниз у каждого", "moves": [round(-6 * float(s), 4) for s in sigma]})
    return out
