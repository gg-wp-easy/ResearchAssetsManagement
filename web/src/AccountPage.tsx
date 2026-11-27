import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type AccountCosts, type AccountResult, type AccountRow, type AccountSettings, type BookRequest } from "./api";
import { Chart, timeLines } from "./charts";
import { day, num, pct } from "./format";
import { useTheme } from "./theme";
import { Card, Note, Segmented, TableWrap, Tile, V } from "./ui";
import { Guide, Term } from "./help";
import { EventLine, StatusTag } from "./eventsUi";

const KEY = "ram.account.v1"; // the book's options of this page; the account's settings live on the server
type Opts = Pick<BookRequest, "limit" | "trend" | "equity">;
const OPTS: Opts = { limit: 0.25, trend: "main_guard", equity: "composite" };  // the bot trades the protected rule since 2026-11-27
const FUNDS = { mmf: ["LQDT", "SBMM", "AKMM", "TMON"], bond: ["SBGB", "TOFZ"], index: ["SBMX", "TMOS", "EQMX"] };
const FX = ["USD", "EUR", "CNY"];
const COSTS: [keyof AccountCosts, ReactNode][] = [
  ["stocks", "акции"], ["funds", "фонды и деньги"], ["futures", "фьючерсы"], ["fixed", "тариф"],
  ["drag", <Term k="fund_drag" key="d">отставание фондов</Term>], ["div_tax", "налог с дивидендов"], ["income_tax", "НДФЛ за год"],
];

function savedOpts(): Opts {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (v && typeof v.limit === "number") return { ...OPTS, ...v };
  } catch { /* storage blocked */ }
  return OPTS;
}

const rub = (x: number | null | undefined, sign = false): string => {
  if (typeof x !== "number" || !Number.isFinite(x)) return "—";
  const s = Math.round(Math.abs(x)).toLocaleString("ru-RU") + " ₽";
  return x < 0 ? "−" + s : sign && x > 0 ? "+" + s : s;
};
const fine = (x: number) => Math.round(x * 1e6) / 1e6;

function NumField({ label, value, onChange, step = 1, scale = 1, suffix, min = 0 }: {
  label: ReactNode; value: number; onChange: (v: number) => void; step?: number; scale?: number; suffix?: string; min?: number;
}) {
  return (
    <label className="field num-field">
      <span>{label}</span>
      <span className="num-in">
        <input type="number" min={min} step={step} value={fine(value * scale)} onChange={(e) => onChange(Number(e.target.value) / scale)} />
        {suffix && <small>{suffix}</small>}
      </span>
    </label>
  );
}

export function AccountPage() {
  const [opts, setOpts] = useState<Opts>(savedOpts);
  const [saved, setSaved] = useState<AccountSettings | null>(null);
  const [draft, setDraft] = useState<AccountSettings | null>(null);
  const [res, setRes] = useState<AccountResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = (o: Opts) => {
    setBusy(true);
    setError("");
    try { localStorage.setItem(KEY, JSON.stringify(o)); } catch { /* storage blocked */ }
    api.account(o).then(setRes).catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
  };
  useEffect(() => {
    api.accountSettings().then((s) => { setSaved(s); setDraft(s); }).catch((e) => setError((e as Error).message));
    run(opts);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(saved);
  const apply = async () => {
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      const clean = { ...draft, funds: draft.funds.filter((f) => f.secid.trim()) };
      const s = await api.saveAccountSettings(clean);
      setSaved(s);
      setDraft(s);
      setRes(await api.account(opts));
      try { localStorage.setItem(KEY, JSON.stringify(opts)); } catch { /* storage blocked */ }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const set = <K extends keyof AccountSettings>(k: K, v: AccountSettings[K]) => draft && setDraft({ ...draft, [k]: v });

  return (
    <div className="lab">
      <header className="lab-head">
        <h1>Мой счёт</h1>
        <p>Портфель из блоков на отдельном счёте Т-Банка: целые лоты акций и контракты фьючерсов, твои комиссии и тариф, отставание фондов от индексов, налог 13%. Здесь же план покупок на сегодня и весь капитал вместе с подушкой вне счёта (физическое золото, наличная валюта, фонды недвижимости) в тех же сценариях.</p>
      </header>
      <Guide id="account" />

      {draft && (
        <Card title="Счёт и тариф" sub="Сохраняется на сервере (data/user/account.json, вне git) и используется расчётом и командой ram account.">
          <div className="lab-controls">
            <NumField label="Деньги на бумаги" value={draft.money} step={10000} suffix="₽" onChange={(v) => set("money", v)} />
            <NumField label={<Term k="variation_margin">Под фьючерсы</Term>} value={draft.futures_money} step={10000} suffix="₽" onChange={(v) => set("futures_money", v)} />
            <NumField label="Комиссия: акции, облигации, фонды" value={draft.fee} step={0.005} scale={100} suffix="%" onChange={(v) => set("fee", v)} />
            <NumField label="Комиссия: фьючерсы" value={draft.fee_fut} step={0.005} scale={100} suffix="%" onChange={(v) => set("fee_fut", v)} />
            <NumField label="Тариф" value={draft.fee_month} step={10} suffix="₽/мес" onChange={(v) => set("fee_month", v)} />
            <NumField label="Налог" value={draft.tax} step={1} scale={100} suffix="%" onChange={(v) => set("tax", v)} />
          </div>
          <div className="lab-controls book-budget">
            <label className="field">
              <span>Деньги — фонд</span>
              <select value={draft.mmf} onChange={(e) => set("mmf", e.target.value)}>{FUNDS.mmf.map((f) => <option key={f}>{f}</option>)}</select>
            </label>
            <label className="field">
              <span>ОФЗ — фонд</span>
              <select value={draft.bond_fund} onChange={(e) => set("bond_fund", e.target.value)}>{FUNDS.bond.map((f) => <option key={f}>{f}</option>)}</select>
            </label>
            <div className="field">
              <span><Term k="bonds_futures">Облигации</Term></span>
              <Segmented label="Чем держать облигации" value={draft.bonds}
                options={[{ value: "fund", label: "фондом" }, { value: "futures", label: "фьючерсом RB" }]}
                onChange={(v) => set("bonds", v)} />
            </div>
            <div className="field">
              <span><Term k="trend_exec">Тренд</Term></span>
              <Segmented label="Кто ведёт тренд" value={draft.trend_exec}
                options={[{ value: "daily", label: "бот каждый день" }, { value: "weekly", label: "руками раз в неделю" }]}
                onChange={(v) => set("trend_exec", v)} />
            </div>
          </div>
          <div className="lab-controls book-budget">
            <label className="field">
              <span><Term k="scenario_cap">Предел потерь в сценарии</Term></span>
              <select value={opts.limit} onChange={(e) => setOpts({ ...opts, limit: Number(e.target.value) })}>
                {[0, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50].map((v) => <option key={v} value={v}>{v ? pct(v, 0) + " капитала" : "без предела"}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Тренд бота</span>
              <select value={opts.trend} onChange={(e) => setOpts({ ...opts, trend: e.target.value })}>
                <option value="main">основной счёт бота</option><option value="main_guard">основной с защитой</option>
              </select>
            </label>
            <label className="field">
              <span>Акции</span>
              <select value={opts.equity} onChange={(e) => setOpts({ ...opts, equity: e.target.value })}>
                <option value="composite">отбор: моментум, низкая волатильность, E/P, FCF/P</option>
                <option value="gbm">отбор: ML-бустинг</option><option value="ew">100 бумаг поровну</option>
                <option value="mcftr">индексный фонд</option>
              </select>
            </label>
            {opts.equity === "mcftr" && (
              <label className="field">
                <span>Индексный фонд</span>
                <select value={draft.index_fund} onChange={(e) => set("index_fund", e.target.value)}>{FUNDS.index.map((f) => <option key={f}>{f}</option>)}</select>
              </label>
            )}
          </div>
          <h4 className="sub-head"><Term k="cushion">Подушка вне счёта</Term> — только для оценки</h4>
          <div className="lab-controls">
            <NumField label="Физическое золото" value={draft.gold_grams} step={10} suffix="г" onChange={(v) => set("gold_grams", v)} />
            <NumField label="Скидка банка при продаже золота" value={draft.gold_haircut} step={1} scale={100} suffix="%" onChange={(v) => set("gold_haircut", v)} />
            {FX.map((c) => (
              <NumField key={c} label={`Наличные ${c}`} value={draft.fx[c] ?? 0} step={100} suffix={c}
                onChange={(v) => set("fx", { ...draft.fx, [c]: v })} />
            ))}
            <NumField label="Скидка при обмене валюты" value={draft.fx_haircut} step={0.5} scale={100} suffix="%" onChange={(v) => set("fx_haircut", v)} />
          </div>
          <div className="acc-funds">
            <p className="hint">Фонды недвижимости (ЗПИФ): код на Мосбирже, число паёв и выплаты в год (биржа их не отдаёт — возьми из отчёта фонда). Например, RU000A1022Z1 — ПАРУС-ОЗН, XXXXXX — Рентал ПРО.</p>
            {draft.funds.map((f, i) => (
              <div key={i} className="lab-controls acc-fund">
                <label className="field"><span>Код</span>
                  <input value={f.secid} placeholder="RU000A1022Z1" onChange={(e) => set("funds", draft.funds.map((x, j) => j === i ? { ...x, secid: e.target.value.toUpperCase().trim() } : x))} /></label>
                <NumField label="Паёв" value={f.units} step={1} onChange={(v) => set("funds", draft.funds.map((x, j) => j === i ? { ...x, units: v } : x))} />
                <NumField label="Выплаты в год" value={f.payout} step={0.5} scale={100} suffix="%" min={-50}
                  onChange={(v) => set("funds", draft.funds.map((x, j) => j === i ? { ...x, payout: v } : x))} />
                <button type="button" className="ghost small" onClick={() => set("funds", draft.funds.filter((_, j) => j !== i))}>убрать</button>
              </div>
            ))}
            <button type="button" className="ghost small" onClick={() => set("funds", [...draft.funds, { secid: "", units: 0, payout: 0 }])}>+ фонд недвижимости</button>
          </div>
          <div className="acc-apply">
            <button type="button" className="primary" disabled={busy} onClick={apply}>{busy ? "Считаю…" : dirty ? "Сохранить и посчитать" : "Посчитать"}</button>
            <span className="hint">Счёт: {rub(draft.money + draft.futures_money)}. Первый расчёт собирает блоки (до пары минут без кэша), дальше — секунды.</span>
          </div>
        </Card>
      )}

      {error && <Note kind="warn">Не посчиталось: {error}</Note>}
      {!res && busy && <div className="loading"><div className="spinner" /></div>}
      {res && <AccountView r={res} stale={busy} />}
    </div>
  );
}

function AccountView({ r, stale }: { r: AccountResult; stale: boolean }) {
  const row = (k: string) => r.rows.find((x) => x.key === k);
  const ideal = row("ideal")!, live = row("live")!, money = row("money")!;
  const c = live.costs!;
  const spend = c.stocks + c.funds + c.futures + c.fixed + c.drag;
  return (
    <div className={stale ? "stale" : ""}>
      <p className="period">{day(r.meta.from)} – {day(r.meta.to)} · {num(r.meta.years, 1)} года · счёт {rub(live.capital)} с первой недели портфеля из блоков · лоты и фьючерсы — на {day(r.meta.specs_date)}</p>
      {r.meta.notes.length > 0 && <Note kind="warn"><ul>{r.meta.notes.map((n) => <li key={n}>{n}</li>)}</ul></Note>}
      <div className="tiles">
        <Tile label="Твой счёт до налогов" value={pct(live.cagr, 1, true)} sub={`без лотов и твоих издержек ${pct(ideal.cagr, 1)}`} />
        <Tile label="После налогов" value={pct(live.after_tax_cagr, 1, true)} sub="НДФЛ каждый год и при продаже в конце" />
        <Tile label={<>Деньги в {r.settings.mmf}</>} value={pct(money.cagr, 1, true)} sub={<>после налога {pct(money.after_tax_cagr, 1)}; с <Term k="ldv">ЛДВ</Term> — без налога</>} />
        <Tile label={<Term k="dd">Наибольшая просадка</Term>} value={pct(live.dd, 1)} sub={`без лотов ${pct(ideal.dd, 1)}`} />
        <Tile label="Издержки в год" value={pct(spend, 2)} sub="комиссии, спред, тариф, фонды" />
        <Tile label={<Term k="go">ГО сегодня</Term>} value={rub(r.plan.margin)} sub={`из ${rub(r.plan.futures_money)} под фьючерсы`} />
      </div>
      <Plan r={r} />
      <Variants r={r} />
      <Costs r={r} />
      <Growth r={r} />
      <Wealth r={r} />
      <Funds r={r} />
      <Note>
        <p><b>Как считается.</b> Каждую неделю с {day(r.meta.from)} счёт держит доли портфеля из блоков (с теми же решениями, срезами и пределом) так, как их можно купить: отобранные акции — целыми лотами сегодняшнего размера по ценам недели, облигации и деньги — паями фондов ({r.settings.bond_fund}, {r.settings.mmf}) с их <Term k="fund_drag">отставанием от индекса</Term> за последние годы ({r.settings.bond_fund} {pct(r.meta.drags.bond.drag, 2)}, {r.settings.mmf} {pct(r.meta.drags.mmf.drag, 2)}, {r.settings.index_fund} {pct(r.meta.drags.index.drag, 2)} в год), фьючерсы — целыми контрактами; цена контракта в прошлом — сегодняшняя, пересчитанная по цене рынка. Всё, что не в акциях и фонде облигаций, лежит в фонде денег, через него идёт и <Term k="variation_margin">вариационная маржа</Term>.</p>
        <p><b>Тренд.</b> «Бот каждый день» — доходность тренд-блока как у бота плюс ошибка целых контрактов; «руками раз в неделю» — позиции на конец недели держатся неделю, комиссия — за каждый изменённый контракт. Издержки самого бота в его блоке — 0,04% и тик, как в его бэктесте (у тебя 0,025%: небольшой запас).</p>
        <p><b>Налоги.</b> 13% с дивидендов удерживаются сразу. Реализованный результат года (продажи акций и паёв по средней цене покупки, вариационная маржа, минус комиссии и тариф) облагается в январе, убыток переносится на следующие годы. «После налогов» — ещё и налог с нереализованной прибыли, как если бы всё продали в конце. Брокер считает по FIFO, а не по средней цене, — разница небольшая. На <Term k="iis3">ИИС-3</Term> строки НДФЛ не было бы.</p>
        <p><b>Чего здесь нет.</b> Процента за минус по деньгам, если брокер не принимает паи фонда в обеспечение. Спреда в кризис: в 2022 году акции и фонды неделю не торговались. Лотов прошлых лет (берутся сегодняшние, у {r.meta.unknown_lots} бумаг, которых больше нет на бирже, — лот 1).</p>
      </Note>
    </div>
  );
}

function Plan({ r }: { r: AccountResult }) {
  const p = r.plan;
  const W = ["акции", "облигации", "тренд", "деньги"];
  const stocks = p.rows.filter((x) => x.kind === "share");
  return (
    <Card title={`План на сегодня: что держать на ${rub(p.capital)}`}
      sub={<>Доли портфеля из блоков на {day(p.date)}: {W.map((w, i) => `${w} ${pct(p.weights[i], 0)}`).join(", ")}. Отклонение — от цели в рублях из-за <Term k="lot_rounding">целых лотов</Term>{stocks.length ? `: ${p.off} из ${stocks.length} бумаг дальше 25% от цели, в сумме ${pct(p.rounding, 0)} блока акций.` : "."}</>}>
      <TableWrap label="План: бумаги и фонды">
        <table className="compact">
          <thead><tr><th>Бумага</th><th className="r">Лотов × лот</th><th className="r">Цена</th><th className="r">Сумма</th><th className="r">Цель</th><th className="r" title="жирным — дальше 25% от цели">Отклонение</th><th>События</th></tr></thead>
          <tbody>
            {p.rows.map((x) => (
              <tr key={x.code}>
                <td><b>{x.code}</b> <span className="muted">{x.name}</span></td>
                <td className="r nowrap">{x.lots.toLocaleString("ru-RU")} × {x.lot.toLocaleString("ru-RU")}</td>
                <td className="r">{num(x.price, x.price < 10 ? 4 : 2)}</td>
                <td className="r nowrap">{rub(x.value)}</td>
                <td className="r nowrap">{rub(x.target)}</td>
                <td className={"r" + (x.kind === "share" && x.target && Math.abs(x.value / x.target - 1) > 0.25 ? " dev-off" : "")}>
                  {x.kind === "share" && x.target ? pct(x.value / x.target - 1, 0, true) : ""}</td>
                <td>{x.status && x.status !== "ok" ? <><StatusTag status={x.status} /> {x.events?.[0] && <EventLine e={x.events[0]} />}</> : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <TableWrap label="План: фьючерсы">
        <table className="compact">
          <thead><tr><th>Фьючерс</th><th className="r">Контрактов</th><th className="r">Номинал</th><th className="r">Цель</th><th className="r"><Term k="go">ГО</Term></th></tr></thead>
          <tbody>
            {p.futures.map((f) => (
              <tr key={f.code}>
                <td><b>{f.code}</b> <span className="muted">{f.market}</span></td>
                <td className="r">{f.contracts === 0 ? "0" : `${f.contracts > 0 ? "лонг" : "шорт"} ${Math.abs(f.contracts)}`}</td>
                <td className="r">{rub(f.notional)}</td>
                <td className="r">{rub(f.target)}{Math.abs(f.target - f.trend) > 1 ? <small className="muted"> (тренд {rub(f.trend)})</small> : ""}</td>
                <td className="r">{rub(f.margin)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Покупка с нуля стоит около {rub(p.entry_cost)} комиссий и спреда. ГО фьючерсов — {rub(p.margin)} ({pct(p.margin_share, 1)} счёта); остальное из {rub(p.futures_money)} под фьючерсы лежит в фонде денег. Вариационная маржа списывается рублями каждый день: держи в рублях ГО и запас на неделю движения, остальное — в фонде. Тренд-блок у бота торгуется каждый день; план показывает позиции на конец недели.</p>
    </Card>
  );
}

function Variants({ r }: { r: AccountResult }) {
  const rows = r.rows;
  return (
    <Card title="Что меняет каждая настройка" sub="Все строки — на одних неделях. «До налогов» — с налогами, вернувшимися в счёт; «после» — НДФЛ каждый год и с остатка прибыли при продаже в конце. «Отличие» — разброс недельной доходности от расчёта без лотов, в год.">
      <TableWrap label="Варианты счёта">
        <table className="compact">
          <thead><tr><th>Вариант</th><th className="r">Счёт</th><th className="r">До налогов</th><th className="r">После</th><th className="r">Вол.</th><th className="r">Просадка</th>
            <th className="r" title="разброс недельной доходности от расчёта без лотов и издержек">Отличие</th><th className="r" title="отклонение блока акций от цели из-за целых лотов">Лоты</th><th className="r">Сделок в год</th></tr></thead>
          <tbody>
            {rows.map((x: AccountRow) => (
              <tr key={x.key} className={x.kind === "live" ? "me" : ""}>
                <td>{x.title}</td>
                <td className="r nowrap">{rub(x.capital)}</td>
                <td className="r"><V x={x.cagr} f={(v) => pct(v, 1, true)} /></td>
                <td className="r">{x.after_tax_cagr === null || x.after_tax_cagr === undefined ? "" : pct(x.after_tax_cagr, 1, true)}</td>
                <td className="r">{pct(x.vol, 1)}</td>
                <td className="r">{pct(x.dd, 1)}</td>
                <td className="r">{x.tracking ? pct(x.tracking, 1) : ""}</td>
                <td className="r">{x.rounding ? pct(x.rounding, 0) : ""}</td>
                <td className="r">{x.trades_year ? num(x.trades_year, 0) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Фонд денег на истории — {pct(row(rows, "money")?.cagr, 1)} в год; паи, которые держишь больше трёх лет, по <Term k="ldv">ЛДВ</Term> освобождаются от налога, поэтому после налогов портфель обгоняет его меньше, чем до.</p>
    </Card>
  );
}

const row = (rows: AccountRow[], k: string) => rows.find((x) => x.key === k);

function Costs({ r }: { r: AccountResult }) {
  const rows = r.rows.filter((x) => x.costs);
  return (
    <Card title="Куда уходят деньги" sub="В год, доля среднего капитала счёта. Тариф — фиксированная плата: на маленьком счёте это главная статья.">
      <TableWrap label="Издержки и налоги">
        <table className="compact">
          <thead><tr><th>Вариант</th>{COSTS.map(([k, t]) => <th key={k} className="r">{t}</th>)}<th className="r">без налогов</th></tr></thead>
          <tbody>
            {rows.map((x) => {
              const c = x.costs!;
              return (
                <tr key={x.key} className={x.kind === "live" ? "me" : ""}>
                  <td>{x.title}</td>
                  {COSTS.map(([k]) => <td key={k} className="r">{c[k] > 5e-5 ? pct(c[k], 2) : "—"}</td>)}
                  <td className="r">{pct(c.stocks + c.funds + c.futures + c.fixed + c.drag, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Тариф {rub(r.settings.fee_month)} в месяц — на весь брокерский договор: если он уже платится за счёт бота, второй счёт его не удваивает (поставь 0). У фонда {r.settings.mmf} комиссия за сделку та же, что у акций; при каждой покупке акций или облигаций продаются паи фонда денег — отсюда строка «фонды и деньги».</p>
    </Card>
  );
}

function Growth({ r }: { r: AccountResult }) {
  const t = useTheme();
  const S = r.series;
  const opt = useMemo(() => timeLines(t, S.dates, [
    { name: "портфель из блоков без лотов и издержек", values: S.ideal, color: t.series[6], width: 2 },
    { name: "твой счёт до налогов", values: S.live, color: t.series[1], width: 2.5, z: 5 },
    { name: `деньги в ${r.settings.mmf}`, values: S.money, color: t.gray, width: 2, dashed: true },
  ], { log: true, yFmt: (v) => num(v, 1), tipFmt: (v) => num(v, 2), zoom: true }), [t, r]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Card title="Рост капитала" sub="Логарифмическая шкала, 1 — начало. Налоги здесь не вычтены: так линии сравнимы с расчётом без лотов.">
      <Chart option={opt} height={320} label="Рост капитала: портфель без лотов, твой счёт, деньги" />
    </Card>
  );
}

function Wealth({ r }: { r: AccountResult }) {
  const w = r.wealth;
  if (w.items.length < 2) {
    return (
      <Card title="Весь капитал вместе с подушкой">
        <p className="hint">Добавь выше физическое золото, наличную валюту и фонды недвижимости — здесь появится, как весь капитал проходит те же сценарии, что и счёт.</p>
      </Card>
    );
  }
  return (
    <Card title={`Весь капитал: ${rub(w.total)}`} sub={<><Term k="cushion">Подушка</Term> (золото и наличная валюта) — {rub(w.cushion)}, {pct(w.cushion_share, 0)} капитала. Сценарии — те же, что держит предел счёта, на сегодняшних долях и позициях.</>}>
      <TableWrap label="Состав капитала">
        <table className="compact">
          <thead><tr><th>Что</th><th>Как оценено</th><th className="r">Стоимость</th><th className="r">При продаже</th><th className="r">Доля</th></tr></thead>
          <tbody>
            {w.items.map((i) => (
              <tr key={i.label}><td>{i.label}</td><td className="muted">{i.detail ?? ""}</td><td className="r">{rub(i.value)}</td><td className="r">{rub(i.sale)}</td><td className="r">{pct(i.share, 0)}</td></tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <TableWrap label="Капитал в сценариях">
        <table className="compact">
          <thead><tr><th>Сценарий</th><th className="r">Счёт</th><th className="r">Золото</th><th className="r">Валюта</th><th className="r">Фонды</th><th className="r">Всего</th><th className="r">Капитала</th></tr></thead>
          <tbody>
            {w.scenarios.map((s) => (
              <tr key={s.label}>
                <td>{s.label}{s.kind === "hist" && s.to ? <span className="muted"> · до {day(s.to)}</span> : ""}</td>
                <td className="r"><V x={s.account} f={(v) => rub(v, true)} /></td>
                <td className="r"><V x={s.gold} f={(v) => (v ? rub(v, true) : "")} /></td>
                <td className="r"><V x={s.fx} f={(v) => (v ? rub(v, true) : "")} /></td>
                <td className="r"><V x={s.funds} f={(v) => (v ? rub(v, true) : "")} /></td>
                <td className="r"><b><V x={s.total} f={(v) => rub(v, true)} /></b></td>
                <td className="r"><V x={s.share} f={(v) => pct(v, 1, true)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      {w.notes.length > 0 && <ul className="foot">{w.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      <p className="foot">Счёт в обвале рубля теряет немного: тренд в шорте юаня и золота — на ограниченную долю, а предел сценариев режет его заранее. Подушка в рублях в такой сценарий дорожает — она и есть страховка от дефолта и девальвации, которой счёт сам себе не даёт. В сценарии «укрепление рубля» она дешевеет.</p>
    </Card>
  );
}

function Funds({ r }: { r: AccountResult }) {
  const f = r.wealth.funds;
  if (!f.length) return null;
  return (
    <Card title="Фонды недвижимости" sub="Биржевая цена пая на неделях портфеля из блоков; выплаты — как ты их указал. Цена пая сглажена редкими сделками и оценкой объектов: колебания и связь с рынком на ней занижены.">
      <TableWrap label="Фонды недвижимости">
        <table className="compact">
          <thead><tr><th>Фонд</th><th>Торгуется с</th><th className="r">Цена пая, в год</th><th className="r">Выплаты</th><th className="r">Итого</th><th className="r">Вол.</th><th className="r">Просадка</th>
            <th className="r" title="Бета к MCFTR (сумма за эту и прошлую неделю)">β акций</th><th className="r" title="Бета к ОФЗ">β ОФЗ</th><th className="r">Стоимость</th></tr></thead>
          <tbody>
            {f.map((x) => (
              <tr key={x.secid}>
                <td><b>{x.name}</b> <span className="muted">{x.secid}</span></td>
                <td className="nowrap">{day(x.first)}</td>
                <td className="r"><V x={x.price_cagr} f={(v) => pct(v, 1, true)} /></td>
                <td className="r">{pct(x.payout, 1)}</td>
                <td className="r"><V x={x.total} f={(v) => pct(v, 1, true)} /></td>
                <td className="r">{pct(x.vol, 1)}</td>
                <td className="r">{pct(x.dd, 1)}</td>
                <td className="r">{num(x.beta_eq, 2)}{x.assumed ? "*" : ""}</td>
                <td className="r">{num(x.beta_bd, 2)}{x.assumed ? "*" : ""}</td>
                <td className="r">{rub(x.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      {f.some((x) => x.assumed) && <p className="foot">* меньше полугода цен — беты приняты, а не оценены.</p>}
    </Card>
  );
}
