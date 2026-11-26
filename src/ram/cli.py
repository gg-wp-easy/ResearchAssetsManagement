"""ram serve | study | fetch | search."""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ram", description="Исследование управления активами")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="сайт и API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    st = sub.add_parser("study", help="исследование корзины в консоли")
    st.add_argument("--preset", default="main")
    st.add_argument("--json", help="сохранить полный результат в файл")
    f = sub.add_parser("fetch", help="скачать ряды в кэш")
    f.add_argument("ids", nargs="+")
    q = sub.add_parser("search", help="найти актив")
    q.add_argument("query")
    fl = sub.add_parser("factors", help="факторная лаборатория акций Мосбиржи")
    fl.add_argument("--start", default="2015-01-01")
    fl.add_argument("--top", type=int, default=100, help="самых ликвидных бумаг во вселенной")
    fl.add_argument("--cost", type=float, default=0.002, help="издержки за сторону сделки")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("ram.api:app", host=a.host, port=a.port, reload=a.reload)
        return 0
    if a.cmd == "fetch":
        from . import sources
        for i in a.ids:
            x = sources.load(i, max_age_hours=0)
            print(f"{i}: {x.name}, {x.dates[0]}..{x.dates[-1]}, {len(x.dates)} дн.")
        return 0
    if a.cmd == "search":
        from . import sources
        for r in sources.search(a.query):
            print(f"{r['id']:32} {r['source']:9} {r['kind']:22} {r['name']}")
        return 0
    if a.cmd == "factors":
        from .factors import lab
        res = lab(a.start, a.top, a.cost)
        m = res["meta"]
        print(f"Факторы: {m['from']}..{m['to']}, {m['months']} мес., {m['top']} самых ликвидных бумаг, "
              f"издержки {m['cost']:.2%} за сторону")
        print(f"  {'фактор':26}{'мес':>5}{'IC':>7}{'t':>6}{'Q1':>7}{'Q5':>7}{'Q5−Q1':>8}{'t':>6}{'Q5−все':>8}{'нетто':>8}{'оборот':>8}")
        for r in sorted(res["factors"], key=lambda r: -abs(r["ic_t"] or 0)):
            print(f"  {r['title']:26}{r['months']:5d}{r['ic']:+7.3f}{r['ic_t']:+6.1f}{r['q'][0]:+7.1%}{r['q'][4]:+7.1%}"
                  f"{r['ls']:+8.1%}{r['ls_t']:+6.1f}{r['ex']:+8.1%}{r['net']:+8.1%}{r['turnover']:8.0%}"
                  + ("  *" if r["sig"] else ""))
        t = res["testing"]
        print(f"  * |t(IC)| > {t['bonferroni']:.2f} (Бонферрони на {t['k']} факторов); медиана лучшего |t| шума {t['noise_max']:.2f}")
        for fm in res["fm"]:
            print(f"  Фама–Макбет, {fm['title']} ({fm['from']}..{fm['to']}, {fm['months']} мес., R² {fm['r2']:.2f}): "
                  + ", ".join(f"{x['title']} {x['coef']:+.1%} (t {x['t']:+.1f})" for x in fm["rows"]))
        for w in m["warnings"]:
            print("  !", w)
        return 0
    if a.cmd == "study":
        from .presets import PRESETS
        from .study import run_study
        pr = next((p for p in PRESETS if p["key"] == a.preset), None)
        if pr is None:
            print("пресеты: " + ", ".join(p["key"] for p in PRESETS), file=sys.stderr)
            return 2
        req = {k: pr[k] for k in ("assets", "params", "control", "history_from", "period", "start") if k in pr}
        res = run_study(req)
        if a.json:
            with open(a.json, "w") as fh:
                json.dump(res, fh, ensure_ascii=False)
        m, r = res["meta"], res["rule"]
        print(f"{pr['title']}: {m['period']['from']}..{m['period']['to']} ({m['period']['years']:.1f} лет)")
        main = "портфель" if m["mode"] == "portfolio" else "правило"
        for name, k in ((main, "book"), (m["bench"], "hold")):
            x = r[k]
            print(f"  {name:8} в год {x['cagr']:+.1%}, вол. {x['vol']:.1%}, Шарп {x['sharpe']:.2f}, просадка {x['dd']:.1%}, "
                  f"худший день {x['worst_day']:+.1%} ({x['worst_day_date']})")
        for w in m["warnings"]:
            print("  !", w)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
