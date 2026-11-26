"""The trade bot's stress test (project-trade-t-bot research/stress_scenarios.py, 2026-11-26) redone with this library
on its own data (Bank of Russia rates instead of Yahoo's RUB=X, see README "Чем сайт отличается").

Sections as in the bot: A history and crisis windows, B scenarios on today's positions, C tails, D drawdown control and
the bootstrap, F a smaller short of the yuan and gold, G both changes together (the paper account main_guard).

Run: .venv/bin/python research/main_book.py [A B C D F G]
"""
from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np

from ram.assets import AssetSpec, build
from ram.bootstrap import drawdown_odds
from ram.metrics import perf, weekly_t
from ram.presets import MAIN_BOOK
from ram.rule import CONTROLS, Params, capped, full_size_today, signal, simulate, weights_today
from ram.scenarios import BOT_HYPOTHETICAL, crisis_table, scenario_moves
from ram.tails import asset_tails, tail_numbers

START = "2006-02-01"  # about the bot's 300 trading days of warm-up from 2004-12-01


def line(name: str, x: np.ndarray, days: list[str], ppy: float, base: np.ndarray | None = None) -> str:
    s = perf(x, days, ppy)
    out = (f"  {name:38}{s['cagr']:+7.1%}{s['sharpe']:7.2f}{s['dd']:9.1%}{s['worst_month']:+10.1%}{s['worst_year']:+10.1%}")
    if base is not None:
        out += f"   {(x - base).mean() * ppy:+6.1%} в год, t {weekly_t(days, x - base):+.1f}"
    return out


HEAD = f"  {'':38}{'в год':>7}{'Шарп':>7}{'просадка':>9}{'худш. мес':>10}{'худш. год':>10}"


def main() -> None:
    parts = [a.upper() for a in sys.argv[1:]] or list("ABCDFG")
    specs = [AssetSpec.from_dict(a) for a in MAIN_BOOK]
    b = build(specs, "2004-12-01")
    p = Params()
    sig = signal(b, p)
    s0 = b.index_of(START)
    days, ppy = b.dates[s0:], b.ppy
    base = simulate(b, p, CONTROLS[0], sig)
    x = base.x[s0:]
    print(f"Основной счёт бота: {days[0]}..{days[-1]}, {len(days) / ppy:.1f} лет, риск 10% на инструмент, ГО до 50%")
    for w in b.warnings:
        print("  !", w)

    if "A" in parts:
        print("\nA. История")
        print(HEAD)
        print(line("правило без контроля", x, days, ppy))
        print(f"\n  {'окно':46}{'счёт':>8}{'худш. день':>11}")
        for c in crisis_table(b, base.x, base.pos, s0):
            if c["traded"]:
                print(f"  {c['label']:46}{c['book']:+8.1%}{c['worst_day']:+11.1%}")

    if "B" in parts:
        full, s = full_size_today(b, p)
        w = weights_today(b, p, s)
        go = np.array([a.go for a in specs])
        print(f"\nB. Сценарии на позициях {b.dates[-1]}: вол. " + ", ".join(f"{l} {v * np.sqrt(ppy):.0%}" for l, v in zip(b.labels, s))
              + "; веса правила " + ", ".join(f"{v:+.2f}" for v in w))
        rule, worst = capped(w * full, go, 0.5), capped(full, go, 0.5)
        print(f"  {'сценарий':52}{'правило':>9}{'худший знак':>13}   (денег на счёте: x2)")
        rows = [(r["label"], [np.nan_to_num(np.array(m, float)) for m in r["moves"]]) for r in scenario_moves(b)]
        rows += [(label, [np.array(m)]) for label, m in BOT_HYPOTHETICAL]
        for label, moves in rows:
            a = min(float(rule @ m) for m in moves)
            z = min(-float(np.abs(worst) @ np.abs(m)) for m in moves)
            print(f"  {label:52}{a:+9.1%}{z:+13.1%}")

    if "C" in parts:
        print("\nC. Хвосты")
        t = tail_numbers(x, ppy)
        print(f"  счёт: xi дня {t['xi']:+.2f}; убыток раз в 1/5/10/20 лет: "
              + " / ".join(f"{o['evt']:.1%}" for o in t["once"][:4]) + " (нормальное: "
              + " / ".join(f"{o['normal']:.1%}" for o in t["once"][:4]) + ")")
        for j, label in enumerate(b.labels):
            a = asset_tails(b.R[:, j])
            print(f"  {label:18} xi падений {a['xi_down']:+.2f}, роста {a['xi_up']:+.2f}, эксцесс {a['kurt']:.1f}")

    if "D" in parts:
        print("\nD. Контроль просадки")
        print(HEAD + "   против без контроля")
        for c in CONTROLS:
            y = simulate(b, p, c, sig).x[s0:]
            print(line(c.name, y, days, ppy, None if c.kind == "none" else x))
        print("\n  Бутстреп (блоки по 21 дню, 4000 путей): P(просадка > 15/25/35%) за 1 и 3 года")
        for o in drawdown_odds(x, [c for c in CONTROLS if not c.rolling], ppy):
            cells = " | ".join(" ".join(f"{v:4.0%}" for v in o["odds"][h].values()) for h in ("1", "3"))
            print(f"    {o['name']:38} {cells}")

    def capped_book(caps: list[float]):
        bb = build([replace(a, short_cap=c) for a, c in zip(specs, caps)], "2004-12-01")
        return bb, signal(bb, p)

    if "F" in parts:
        print("\nF. Шорт юаня и золота")
        print(HEAD + "   против без ограничения")
        for name, caps in (("без ограничения", [1, 1, 1, 1]), ("шорт юаня до 0,5", [0.5, 1, 1, 1]),
                           ("шорт юаня и золота до 0,5", [0.5, 0.5, 1, 1]), ("юань и золото только лонг", [0, 0, 1, 1])):
            bb, sg = capped_book(caps)
            y = simulate(bb, p, CONTROLS[0], sg).x[s0:]
            print(line(name, y, days, ppy, None if caps == [1, 1, 1, 1] else x))

    if "G" in parts:
        print("\nG. Обе меры вместе (main_guard) против правила бота со стопом")
        print(HEAD + "   против правила бота")
        bot = simulate(b, p, CONTROLS[1], sig).x[s0:]
        print(line("правило бота (стоп 25%)", bot, days, ppy))
        bb, sg = capped_book([0.5, 0.5, 1, 1])
        print(line("шорт до 0,5", simulate(bb, p, CONTROLS[0], sg).x[s0:], days, ppy, bot))
        print(line("контроль с 10%, без стопа", simulate(b, p, CONTROLS[7], sig).x[s0:], days, ppy, bot))
        print(line("оба (счёт main_guard)", simulate(bb, p, CONTROLS[7], sg).x[s0:], days, ppy, bot))


if __name__ == "__main__":
    main()
