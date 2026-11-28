"""ram serve | study | fetch | search | factors | ml | book | account | events | bonds | valuation."""
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
    mll = sub.add_parser("ml", help="ML-прогноз доходности акций Мосбиржи (скользящее обучение)")
    mll.add_argument("--start", default="2015-01-01")
    mll.add_argument("--top", type=int, default=100)
    mll.add_argument("--cost", type=float, default=0.002)
    bk = sub.add_parser("book", help="портфель из блоков: отбор акций, облигации, тренд бота, деньги")
    bk.add_argument("--equity", default="composite", help="composite | gbm | ew | mcftr")
    bk.add_argument("--bonds", default="ofz", help="ofz | corp")
    bk.add_argument("--trend", default="main", help="main | main_guard")
    bk.add_argument("--budget", default="1,1,1", help="бюджет риска (или доли капитала с --weights): акции,облигации,тренд")
    bk.add_argument("--weights", action="store_true", help="бюджет — доли капитала, а не риска")
    bk.add_argument("--vol", type=float, default=0.10, help="целевая волатильность в год")
    bk.add_argument("--limit", type=float, default=0.25, help="предел потерь в любом сценарии (0 — без предела)")
    bk.add_argument("--control", type=int, default=0, help="контроль просадки: номер из списка правила")
    bk.add_argument("--start", default="2016-01-01")
    ac = sub.add_parser("account", help="портфель из блоков на счёте Т-Банка: лоты, контракты, комиссии, налог, подушка")
    ac.add_argument("--limit", type=float, default=0.25, help="предел потерь в любом сценарии (0 — без предела)")
    ac.add_argument("--trend", default="main_guard", help="main_guard (как бот с 2026-11-27) | main")
    ac.add_argument("--equity", default="composite", help="composite | gbm | ew | mcftr")
    ac.add_argument("--bonds", default="own", help="own (свои выпуски по режиму ЦБ) | ofz (фонд или фьючерс RB) | corp")
    ac.add_argument("--set", nargs="*", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                    help="настройки счёта на этот расчёт (money=200000 bonds=futures trend_exec=weekly ...)")
    ac.add_argument("--save", action="store_true", help="сохранить --set в data/user/account.json")
    ac.add_argument("--export", metavar="ФАЙЛ", help="только записать план для бота (доли, лоты, цены) в JSON-файл")
    ca = sub.add_parser("capital", help="весь капитал: счёт, золото, валюта, фонды недвижимости; планы долей")
    ca.add_argument("--limit", type=float, default=0.25, help="предел потерь портфеля из блоков в любом сценарии")
    ca.add_argument("--trend", default="main_guard", help="main_guard | main")
    ca.add_argument("--equity", default="composite", help="composite | gbm | ew | mcftr")
    ca.add_argument("--bonds", default="own", help="own | ofz | corp")
    ca.add_argument("--set", nargs="*", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                    help="золото и валюта на этот расчёт: gold_grams=100 USD=3000 CNY=20000")
    ev = sub.add_parser("events", help="события Мосбиржи: дефолты, банкротства, делистинг, сектор повышенного риска")
    ev.add_argument("--update", action="store_true", help="перечитать ленту новостей биржи сейчас")
    ev.add_argument("--since", help="дочитать ленту вглубь до даты (по умолчанию — два года)")
    ev.add_argument("--days", type=int, default=30, help="лента за столько дней")
    ev.add_argument("--check", nargs="*", help="проверить бумаги: тикеры или ISIN")
    ev.add_argument("--portfolios", action="store_true", help="проверить портфели SAS и отбор портфеля из блоков")
    ev.add_argument("--stop", nargs="+", metavar=("КОД", "ПРИЧИНА"), help="добавить бумагу в стоп-лист")
    ev.add_argument("--unstop", help="убрать бумагу из стоп-листа")
    bo = sub.add_parser("bonds", help="облигации из выпусков: ОФЗ ПД, ПК, ИН, корпоративные — против индексов и SBGB")
    bo.add_argument("--tax", type=float, default=0.13, help="налог с купонов (0 — ИИС с освобождением дохода)")
    bo.add_argument("--start", default="2014-01-31")
    bo.add_argument("--today", action="store_true", help="показать сегодняшний состав каждого вида")
    va = sub.add_parser("valuation", help="оценка server-analytic-system на дату и сверка с его срезом")
    va.add_argument("--date", default="2025-10-31")
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
    if a.cmd == "ml":
        from .ml import lab as ml_lab
        res = ml_lab(a.start, a.top, a.cost)
        m = res["meta"]
        print(f"ML-прогноз: {m['top']} бумаг, издержки {m['cost']:.2%}, переобучение раз в {m['refit']} мес., "
              f"испытаний (для DSR) {m['trials']}")
        print(f"  {'модель':34}{'мес':>5}{'IC':>7}{'t':>6}{'Q5−все':>8}{'нетто':>8}{'t':>6}{'оборот':>8}{'DSR':>6}")
        for s_ in res["sets"]:
            print(f" {s_['title']}:")
            for r in (r for r in res["rows"] if r["set"] == s_["key"]):
                print(f"  {r['title'][:34]:34}{r['months']:5d}{r['ic']:+7.3f}{r['ic_t']:+6.1f}{r['ex']:+8.1%}{r['net']:+8.1%}"
                      f"{r['net_t']:+6.1f}{r['turnover']:8.0%}{r['dsr'].get('dsr', float('nan')):6.2f}")
        return 0
    if a.cmd == "book":
        from .book import report
        budget = [float(x) for x in a.budget.split(",")]
        if not a.weights:
            budget = [x / sum(budget) for x in budget]
        res = report({"equity": a.equity, "bonds": a.bonds, "trend": a.trend, "budget": budget,
                      "method": "weights" if a.weights else "risk", "target_vol": a.vol, "limit": a.limit,
                      "control": a.control, "start": a.start})
        m = res["meta"]
        print(f"Портфель из блоков: {m['from']}..{m['to']} ({m['weeks']} нед.), предел сценария {a.limit:.0%}, "
              f"цель {a.vol:.0%} в год, контроль: {m['control']}")
        print(f"  {'':44}{'в год':>8}{'вол.':>7}{'Шарп':>6}{'просадка':>10}{'4 нед.':>8}{'худш. сцен.':>12}{'деньги':>8}")
        for r in res["rows"]:
            tail = f"{r['worst_scenario']:12.0%}{r['cash_share']:8.0%}" if r["kind"] == "book" else ""
            print(f"  {r['title'][:44]:44}{r['cagr']:+8.1%}{r['vol']:7.1%}{r['sharpe']:6.2f}{r['dd']:10.1%}"
                  f"{r['worst_4w']:+8.1%}" + tail)
        t = res["tests"]
        print("  разница Шарпа: " + ", ".join(f"против {k} {v['diff']:+.2f} (t {v['t']:+.1f})" for k, v in t.items()
                                              if k != "book" and v))
        td = res["today"]
        print(f"  сегодня {td['date']}: " + ", ".join(f"{n} {w:.0%}" for n, w in zip(m["sleeves"], td["w"]))
              + f"; худший сценарий — {td['scenarios'][0]['label']}: {-td['scenarios'][0]['loss']:+.1%}")
        for r in res["log"][:6]:
            what = {"rebalance": "ребалансировка", "cut": "срез", "adjust": "к цели"}[r["kind"]]
            print(f"  {r['date']} {what}: " + ", ".join(f"{n} {w:.0%}" for n, w in zip(m["sleeves"], r["w"]))
                  + f" · {r['scenario']} {-r['loss_before']:+.0%} → {-r['loss_after']:+.0%}")
        return 0
    if a.cmd == "account":
        from . import account

        def rub(x: float, sign: bool = False) -> str:
            return (f"{x:+,.0f}" if sign else f"{x:,.0f}").replace(",", "\u202f")
        over = {}
        for kv in a.set:
            k, _, v = kv.partition("=")
            over[k] = v if k in ("mmf", "bond_fund", "index_fund", "bonds", "trend_exec", "capital_plan") else float(v)
        if a.save:
            account.save_settings({**account.load_settings().as_dict(), **over})
        if a.export:
            out = account.write_export(a.export, {"opts": {"limit": a.limit, "trend": a.trend, "equity": a.equity,
                                                           "bonds": a.bonds}, "settings": over})
            w = out["weights"]
            print(f"План для бота: {a.export} на {out['date']} (решение {out['decided']}); акции {w['equity']:.0%}, "
                  f"облигации {w['bonds']:.0%}, тренд {w['trend']:.0%}, деньги {w['cash']:.0%}; бумаг {len(out['rows'])}, "
                  f"фьючерсов {len(out['futures'])}")
            if out.get("bond_policy"):
                bp_ = out["bond_policy"]
                print(f"Облигации: режим ЦБ «{bp_['title']}» с {bp_['since']}, ключевая {bp_['key']:.2%}; "
                      + ", ".join(f"{k} {v:.0%}" for k, v in sorted(bp_["mix"].items(), key=lambda x: -x[1])))
            return 0
        res = account.report({"opts": {"limit": a.limit, "trend": a.trend, "equity": a.equity, "bonds": a.bonds},
                              "settings": over})
        m, st, pl = res["meta"], res["settings"], res["plan"]
        print(f"Счёт {rub(st['capital'])} ₽ ({rub(st['money'])} на бумаги, {rub(st['futures_money'])} под фьючерсы), "
              f"{m['from']}..{m['to']}; комиссии {st['fee']:.3%} / фьючерсы {st['fee_fut']:.3%}, тариф "
              f"{st['fee_month']:.0f} ₽/мес, налог {st['tax']:.0%}")
        print(f"  {'':58}{'до налога':>10}{'после':>8}{'вол.':>7}{'просадка':>10}{'лоты':>6}")
        for r in res["rows"]:
            after = r.get("after_tax_cagr")
            print(f"  {r['title'][:58]:58}{r['cagr']:+10.1%}" + (f"{after:+8.1%}" if after is not None else " " * 8)
                  + f"{r['vol']:7.1%}{r['dd']:10.1%}" + (f"{r['rounding']:6.0%}" if r.get("rounding") else ""))
        c = res["live"]["costs"]
        print("  издержки счёта в год: " + ", ".join(f"{k} {v:.2%}" for k, v in c.items()))
        print(f"  план на {pl['date']}: доли " + ", ".join(f"{w:.0%}" for w in pl["weights"])
              + f"; ГО {rub(pl['margin'])} ₽ из {rub(pl['futures_money'])}; вход {rub(pl['entry_cost'])} ₽")
        for r in pl["rows"]:
            print(f"    {r['code']:13}{r['name'][:26]:26}{r['lots']:>8} лот. по {r['lot']:<6}{rub(r['value']):>12} ₽"
                  f"  (цель {rub(r['target'])})" + (f" {r['status']}" if r.get("status", "ok") != "ok" else ""))
        for f in pl["futures"]:
            print(f"    {f['code']:13}{f['market'][:26]:26}{f['contracts']:>+8d} конт.{rub(f['notional']):>12} ₽"
                  f"  ГО {rub(f['margin'])}")
        w = res["wealth"]
        if len(w["items"]) > 1:
            print(f"  капитал вместе с подушкой: {rub(w['total'])} ₽")
            for s_ in w["scenarios"][:5]:
                print(f"    {s_['label'][:46]:46} счёт {rub(s_['account'], True):>12}  вне счёта {rub(s_['total'] - s_['account'], True):>12}"
                      f"  всего {s_['share']:+.1%}")
        return 0
    if a.cmd == "capital":
        from . import account, capital
        over: dict = {}
        fx = dict(account.load_settings().fx)
        for kv in a.set:
            k, _, v = kv.partition("=")
            if k.upper() in account.FX_CODES:
                fx[k.upper()] = float(v)
            else:
                over[k] = float(v)
        over["fx"] = fx
        res = capital.report({"opts": {"limit": a.limit, "trend": a.trend, "equity": a.equity, "bonds": a.bonds},
                              "settings": over})
        t = res["titles"]
        print(f"Весь капитал на {res['date']}: {res['total']:,.0f} ₽ — "
              + ", ".join(f"{t[k]} {res['shares'].get(k, 0):.0%}" for k in res["keys"]))
        g = res["regime"]
        print(f"Режим ЦБ: «{g['title']}» с {g['since']}, ключевая {g['key']:.2%}; бюджет риска по режиму — "
              + ", ".join(f"{t[k]} {v:.0%}" for k, v in g["budget"].items()))
        print(f"\nПланы с {res['start']} (до налогов)   {'в год':>7}{'вол.':>7}{'Шарп':>6}{'просадка':>9}{'сделок/г':>9}"
              f"{'худший сц.':>11}   доли сегодня")
        for p in res["plans"]:
            st = p["stats"]
            print(f"  {p['title'][:32]:32}{st['cagr']:7.1%}{st['vol']:7.1%}{st['sharpe']:6.2f}{st['dd']:9.1%}"
                  f"{p['trades_year']:9.1f}{p['worst_loss']:11.1%}   "
                  + ", ".join(f"{t[k]} {v:.0%}" for k, v in p["today"].items() if v > 0.005))
        print("\nКлассы на тех же неделях:")
        for c in res["classes"]:
            st = c["stats"]
            if st:
                print(f"  {c['title'][:32]:32}{st['cagr']:7.1%}{st['vol']:7.1%}{st['sharpe']:6.2f}{st['dd']:9.1%}")
        print("\nГоды: " + "  ".join(p["key"] for p in res["plans"]))
        for y in res["years"]:
            print(f"  {y['year']} " + "  ".join(f"{y.get(p['key'], float('nan')):+7.1%}" for p in res["plans"]))
        main = res["main"]
        print(f"\nЧто сделать руками по плану «{next(p['title'] for p in res['plans'] if p['key'] == main)}»:")
        for x in res["actions"].get(main, []):
            print("  •", x["text"])
        mk = res["markets"]
        for p in res["plans"]:
            print(f"  {p['title'][:32]:32} рынки: " + ", ".join(f"{mk[k]} {v:+.0%}" for k, v in p["exposure"].items()))
        print(f"\nВалюта с {res['currency']['from']}: наличными или облигациями (в рублях)")
        for x in res["currency"]["rows"]:
            st = x["stats"]
            print(f"  {x['title'][:44]:44}{st['cagr']:7.1%}{st['vol']:7.1%}{st['dd']:9.1%}")
        for n in res["notes"]:
            print("•", n)
        return 0
    if a.cmd == "events":
        from . import events
        if a.update or a.since:
            events.update(since=a.since, force=True, progress=lambda m: print("  " + m, file=sys.stderr))
        if a.stop:
            items = [x for x in events.stoplist() if x["code"] != a.stop[0].upper()]
            events.save_stoplist(items + [{"code": a.stop[0], "reason": " ".join(a.stop[1:])}])
        if a.unstop:
            events.save_stoplist([x for x in events.stoplist() if x["code"] != a.unstop.upper()])
        evs, cov = events.all_events(refresh=not (a.update or a.since))
        print(f"Лента Мосбиржи: {cov['from']}..{cov['to']}, {cov['news']} новостей, прочитано {cov['read']}; "
              f"стоп-лист: {', '.join(x['code'] for x in events.stoplist()) or 'пуст'}")
        if a.check:
            for code, r in events.check(a.check, evs).items():
                print(f"  {code:14} {r['status']:8} {r['issuer'][:50]}")
                for e in r["events"][:5]:
                    print(f"      {e['date']} {e['kind_title']:28} {e['reason'][:90]} {e['detail']}")
            return 0
        if a.portfolios:
            from .watch import portfolios
            for pf in portfolios()["portfolios"]:
                if pf.get("error"):
                    print(f"  {pf['title']}: {pf['error']}")
                    continue
                print(f"  {pf['title']} ({pf['date']}): исключить {pf['excluded']} ({pf['excluded_weight']:.1%} веса), "
                      f"внимание {pf['warned']}")
                for x in pf["positions"]:
                    if x["status"] != "ok":
                        e = x["events"][0]
                        print(f"      {x['status']:8} {x['code']:14} {x['name'][:24]:24} {x['weight']:6.1%} → {x['after']:6.1%}"
                              f"  {e['date']} {e['kind_title']}")
            return 0
        lo = (__import__("datetime").date.today() - __import__("datetime").timedelta(days=a.days)).isoformat()
        for e in [e for e in evs if e.date >= lo and e.level == "exclude"]:
            print(f"  {e.date} {events.KINDS[e.kind][0]:26} {e.issuer[:44]:44} {','.join(e.codes[:2]):28} {e.reason[:60]}")
        return 0
    if a.cmd == "bonds":
        from . import bonds
        rep = bonds.report(a.tax, a.start, progress=lambda w: print(f"  {w}", file=sys.stderr))
        print(f"Облигации из выпусков на {rep['date']}: с {rep['start']} и за 5 лет с {rep['recent_from']}; "
              f"налог с купонов {rep['tax']:.0%} (после налога — колонка «налог»)")
        print(f"{'':48} {'с':>10} {'год. дох.':>9} {'налог':>7} {'волат.':>7} {'просадка':>8} {'Шарп':>5} | "
              f"{'5 лет':>7} {'налог':>7} {'просадка':>8} {'бумаг':>5}")

        def pc(x):
            return f"{x:7.1%}" if x is not None else "      —"
        for r in rep["rows"]:
            w, rc, wt, rt = r["whole"], r["recent"], r["whole_tax"] or {}, r["recent_tax"] or {}
            print(f"{r['title'][:48]:48} {r['from']:>10} {pc(w.get('cagr')):>9} {pc(wt.get('cagr'))} {pc(w.get('vol'))} "
                  f"{pc(w.get('dd')):>8} {w.get('sharpe', 0):5.2f} | {pc(rc.get('cagr'))} {pc(rt.get('cagr'))} "
                  f"{pc(rc.get('dd')):>8} {r['issues'] or 0:5.1f}")
        if a.today:
            for kind, items in rep["today"].items():
                print(f"\n{rep['titles'][kind]}: {len(items)}")
                for b in items:
                    print(f"  {b['secid']:14} {b['name'][:22]:22} цена {b['price']:7.2f}  дох. {pc(b['ytm'])}  "
                          f"дюр. {b['duration'] or 0:4.1f}  спред {pc(b['spread'])}  до погаш./оферты {b['life'] or 0:4.1f} г.")
        for n in rep["notes"]:
            print("•", n)
        return 0
    if a.cmd == "valuation":
        from . import universe, valuation
        p = universe.panel()
        r = valuation.compare_with_sas(p, a.date, valuation.mcftr_weekly(p))
        if r is None:
            print(f"нет среза server-analytic-system на {a.date} или недели {a.date} в данных ISS", file=sys.stderr)
            return 2
        print(f"P/E {a.date}: у нас {r['ours']} компаний, у SAS {r['theirs']}, общих {r['common']}; "
              f"ранговая корреляция P/E {r['multiple_rho']:.4f}, медиана отношения {r['multiple_median_ratio']:.3f}")
        for k, v in r["analyses"].items():
            print(f"  {k:11} ρ отклонений {v['rho']:+.3f} ({v['n']} компаний)")
        print("  R² вне выборки: " + ", ".join(f"{k} {v:.2f}" for k, v in r["r2"].items()))
        print("  отобранные показатели (из 5 блоков): " + ", ".join(f"{k} {v}" for k, v in r["features"].items()))
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
