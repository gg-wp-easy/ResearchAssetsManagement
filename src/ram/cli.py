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
    if a.cmd == "study":
        from .presets import PRESETS
        from .study import run_study
        pr = next((p for p in PRESETS if p["key"] == a.preset), None)
        if pr is None:
            print("пресеты: " + ", ".join(p["key"] for p in PRESETS), file=sys.stderr)
            return 2
        req = {k: pr[k] for k in ("assets", "params", "control", "history_from", "period") if k in pr}
        res = run_study(req)
        if a.json:
            with open(a.json, "w") as fh:
                json.dump(res, fh, ensure_ascii=False)
        m, r = res["meta"], res["rule"]
        print(f"{pr['title']}: {m['period']['from']}..{m['period']['to']} ({m['period']['years']:.1f} лет)")
        for name, k in (("правило", "book"), ("держать", "hold")):
            x = r[k]
            print(f"  {name:8} в год {x['cagr']:+.1%}, вол. {x['vol']:.1%}, Шарп {x['sharpe']:.2f}, просадка {x['dd']:.1%}, "
                  f"худший день {x['worst_day']:+.1%} ({x['worst_day_date']})")
        for w in m["warnings"]:
            print("  !", w)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
