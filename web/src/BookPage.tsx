import { useEffect, useMemo, useState } from "react";
import { api, type BookDecision, type BookRequest, type BookResult, type BookRow, type SharpeDiff } from "./api";
import { axis, base, Chart, legend, legendTop, timeLines, type Option } from "./charts";
import { day, num, pct } from "./format";
import { useTheme, type Theme } from "./theme";
import { Card, Note, Segmented, TableWrap, Tile, V } from "./ui";
import { Guide, Term } from "./help";

const KEY = "ram.book.v1";
const DEFAULT: BookRequest = {
  equity: "composite", bonds: "ofz", trend: "main", method: "risk", budget: [1 / 3, 1 / 3, 1 / 3], target_vol: 0.10,
  limit: 0.25, control: 0, cost: 0.002, start: "2016-01-01",
};
const EQUITY: [string, string][] = [["composite", "отбор: моментум, низкая волатильность, E/P, FCF/P"],
  ["gbm", "отбор: ML-бустинг ценовых факторов"], ["ew", "все 100 бумаг поровну"], ["mcftr", "индекс MCFTR"]];
const BONDS: [string, string][] = [["ofz", "ОФЗ (RGBITR)"], ["corp", "корпоративные (RUCBITR → RUCBTRNS)"]];
const TRENDS: [string, string][] = [["main", "основной счёт бота"], ["main_guard", "основной с защитой"]];
const SLEEVES = ["акции", "облигации", "тренд бота", "деньги"];

function saved(): BookRequest {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (v && typeof v.equity === "string" && Array.isArray(v.budget) && v.budget.length === 3) return { ...DEFAULT, ...v };
  } catch { /* storage blocked */ }
  return DEFAULT;
}

/** Colour of a sleeve (weights, contributions) and of a line in the comparison charts: fixed per entity. */
function sleeveColor(t: Theme, i: number): string {
  return [t.series[0], t.series[1], t.series[2], t.gray][i];
}
function lineColor(t: Theme, key: string): string {
  return ({ book: t.series[6], no_cap: t.series[4], "6040": t.series[3], "equity:mcftr": t.series[0], cash: t.gray } as Record<string, string>)[key]
    ?? (key.startsWith("trend:") ? t.series[2] : t.gray);
}

export function BookPage() {
  const [req, setReq] = useState<BookRequest>(saved);
  const [res, setRes] = useState<BookResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [controls, setControls] = useState<string[]>(["без контроля"]);

  const run = (r: BookRequest) => {
    setBusy(true);
    setError("");
    try { localStorage.setItem(KEY, JSON.stringify(r)); } catch { /* storage blocked */ }
    api.book(r).then(setRes).catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
  };
  useEffect(() => {
    api.meta().then((m) => setControls(m.controls.map((c) => c.name))).catch(() => { /* the list stays short */ });
    run(req);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const share = req.method === "risk";
  const total = req.budget.reduce((a, b) => a + b, 0);
  const budgetBad = !share && total > 1 + 1e-9;
  const setBudget = (i: number, v: number) => {
    const b = [...req.budget] as [number, number, number];
    b[i] = Math.max(0, v) / 100;
    setReq({ ...req, budget: b });
  };
  const shown = (x: number) => Math.round((share && total > 0 ? x / total : x) * 1000) / 10;
  const years = Array.from({ length: 2025 - 2016 }, (_, i) => 2016 + i);
  return (
    <div className="lab">
      <header className="lab-head">
        <h1>Портфель из блоков</h1>
        <p>Акции, отобранные факторной лабораторией, облигации, тренд бота и деньги в одном счёте. Доли задаёт бюджет риска. Предел режет их так, чтобы ни один сценарий из списка не забрал больше заданной доли капитала. Каждое решение принимается только по тому, что было известно на его дату, и записывается в журнал с причиной.</p>
      </header>
      <Guide id="book" />

      <Card>
        <div className="lab-controls">
          <label className="field">
            <span>Акции</span>
            <select value={req.equity} onChange={(e) => setReq({ ...req, equity: e.target.value })}>
              {EQUITY.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Облигации</span>
            <select value={req.bonds} onChange={(e) => setReq({ ...req, bonds: e.target.value })}>
              {BONDS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Тренд</span>
            <select value={req.trend} onChange={(e) => setReq({ ...req, trend: e.target.value })}>
              {TRENDS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <div className="field">
            <span>Доли задаёт</span>
            <Segmented label="Как задаются доли" value={req.method}
              options={[{ value: "risk", label: "бюджет риска" }, { value: "weights", label: "доли капитала" }]}
              onChange={(v) => setReq({ ...req, method: v as BookRequest["method"] })} />
          </div>
        </div>
        <div className="lab-controls book-budget">
          {SLEEVES.slice(0, 3).map((s, i) => (
            <label key={s} className="field num-field">
              <span>{s}, {share ? <Term k="risk_budget">% риска</Term> : "% капитала"}</span>
              <input type="number" min={0} max={100} step={5} value={Math.round(req.budget[i] * 1000) / 10}
                onChange={(e) => setBudget(i, Number(e.target.value))} />
              {share && <small>{num(shown(req.budget[i]), 0)}% после нормировки</small>}
            </label>
          ))}
          {share && (
            <label className="field">
              <span><Term k="target_vol">Цель волатильности</Term></span>
              <select value={req.target_vol} onChange={(e) => setReq({ ...req, target_vol: Number(e.target.value) })}>
                {[0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20].map((v) => <option key={v} value={v}>{pct(v, 0)} в год</option>)}
              </select>
            </label>
          )}
          <label className="field">
            <span><Term k="scenario_cap">Предел потерь в сценарии</Term></span>
            <select value={req.limit} onChange={(e) => setReq({ ...req, limit: Number(e.target.value) })}>
              {[0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50].map((v) => <option key={v} value={v}>{v ? pct(v, 0) + " капитала" : "без предела"}</option>)}
            </select>
          </label>
          <label className="field">
            <span><Term k="control">Контроль просадки счёта</Term></span>
            <select value={req.control} onChange={(e) => setReq({ ...req, control: Number(e.target.value) })}>
              {controls.map((c, i) => <option key={c} value={i}>{c}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Начало</span>
            <select value={req.start} onChange={(e) => setReq({ ...req, start: e.target.value })}>
              {years.map((y) => <option key={y} value={`${y}-01-01`}>{y}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Издержки отбора за сторону</span>
            <select value={req.cost} onChange={(e) => setReq({ ...req, cost: Number(e.target.value) })}>
              {[0, 0.001, 0.002, 0.005].map((c) => <option key={c} value={c}>{pct(c, c ? 1 : 0)}</option>)}
            </select>
          </label>
          <button type="button" className="primary" disabled={busy || budgetBad || !(total > 0)} onClick={() => run(req)}>{busy ? "Считаю…" : "Посчитать"}</button>
        </div>
        {budgetBad && <p className="hint warn-text">Доли капитала в сумме {pct(total, 0)} — больше 100%: без плеча остаток в деньгах не может быть отрицательным.</p>}
        {busy && <p className="hint">Первый расчёт собирает срезы ISS, отбор акций на каждый месяц и правило тренда — до пары минут, если кэша ещё нет; дальше секунды.</p>}
      </Card>

      {error && <Note kind="warn">Не посчиталось: {error}</Note>}
      {!res && busy && <div className="loading"><div className="spinner" /></div>}
      {res && <BookResultView r={res} stale={busy} />}
    </div>
  );
}

function BookResultView({ r, stale }: { r: BookResult; stale: boolean }) {
  const book = r.rows.find((x) => x.key === "book")!;
  const td = r.today;
  const worstNow = td.scenarios[0];
  return (
    <div className={stale ? "stale" : ""}>
      <p className="period">
        {day(r.meta.from)} – {day(r.meta.to)} · {r.meta.weeks} нед. · ребалансировка в конце каждого месяца, ковариация за {r.meta.window} нед. (не меньше {r.meta.min_weeks}) · перенос капитала между блоками {pct(r.meta.rebalance_cost, 1)} за сторону · контроль: {r.meta.control}
      </p>
      {r.meta.notes.length > 0 && (
        <details className="warnings">
          <summary>Замечания к данным: {r.meta.notes.length}</summary>
          <ul>{r.meta.notes.map((w) => <li key={w}>{w}</li>)}</ul>
        </details>
      )}
      <div className="tiles">
        <Tile label="В год" value={pct(book.cagr, 1, true)} sub={`деньги ${pct(r.rows.find((x) => x.key === "cash")?.cagr, 1)}`} />
        <Tile label="Волатильность" value={pct(book.vol, 1)} sub="недельная, в год" />
        <Tile label={<Term k="sharpe">Шарп над деньгами</Term>} value={num(book.sharpe, 2)} sub={`±${num(2 * r.tests.book.se, 2)} (2σ) за ${num(r.tests.book.years, 1)} лет`} />
        <Tile label={<Term k="dd">Наибольшая просадка</Term>} value={pct(book.dd, 1)} sub={`${day(book.dd_from)} – ${day(book.dd_to)}`} />
        <Tile label={<Term k="scenario_cap">Худший сценарий сейчас</Term>} value={pct(worstNow ? -worstNow.loss : null, 1, true)} sub={worstNow?.label} />
        <Tile label="Деньги сейчас" value={pct(td.w[3], 0)} sub={`последнее решение ${day(td.latest)}`} />
      </div>

      <Today r={r} />
      <ScenarioTable r={r} />
      <Compare r={r} />
      <Limits r={r} />
      <Charts r={r} />
      <Years r={r} />
      <Log r={r} />

      <Note>
        <p><b>Как устроено.</b> Каждый конец месяца на последних {r.meta.window} неделях доходностей блоков сверх денег оценивается ковариация Ледуа–Вольфа. По ней ищутся доли, у которых вклады в риск равны бюджету. Доли масштабируются к целевой волатильности без плеча (в сумме не больше 100%), остаток — в деньгах (RUONIA).</p>
        <p><b>Сценарии.</b> Сценарий — совместный ход четырёх рынков тренда бота: юаня, золота в рублях, MCFTR и ОФЗ. Это гипотетические сценарии бота и кризисные окна, закончившиеся до даты решения; длинные окна берутся по каждым 5 дням. Блок акций движется как бета к MCFTR (не меньше 1: в обвал корреляции растут), облигации — как ОФЗ, тренд — как его позиции на эту дату (в гэп их не успеть развернуть).</p>
        <p><b>Предел.</b> Если какой-то сценарий забирает больше предела, линейная программа оставляет как можно больше бюджета риска и режет в первую очередь блок, который теряет больше всего на единицу своего риска. Хедж при этом не трогается. Срез доводит потерю до 95% предела, чтобы дрейф долей не срабатывал на следующей неделе.</p>
        <p><b>Между концами месяцев.</b> Каждую неделю цель месяца (умноженная на множитель контроля просадки) заново проверяется пределом на позициях тренда этой недели. Счёт идёт к цели, если на текущих долях какой-то сценарий превышает предел («срез») или если блок отошёл от цели больше чем на 5 п. п. («к цели»: тренд развернул позиции, сработал контроль, доли уплыли с ценами).</p>
        <p><b>События Мосбиржи.</b> Отбор акций не берёт бумаги с действующим <Term k="exchange_event">событием «продать»</Term> (дефолт, банкротство, делистинг, выкуп, сектор повышенного риска, стоп-лист), а бумагу, о которой новость пришла внутри месяца, продаёт в конце той же недели и делит её долю между остальными. Лента учтена с {day(r.meta.events_from)}; раньше фильтра нет. Строка «без фильтра событий» показывает, что он изменил.</p>
        <p><b>Чего здесь нет.</b> Налогов. Комиссий фондов облигаций (берутся индексы полной доходности). Риска банка или брокера, держащего деньги. Тренд-блок держит свой капитал в деньгах и платит издержки бота; его позиции — доля капитала блока (по ОФЗ полная позиция — около двух капиталов: у ОФЗ малая волатильность). Четыре фактора отбора выбраны факторной лабораторией на той же истории, поэтому отбор «на истории» — не полностью вне выборки.</p>
      </Note>
    </div>
  );
}

function Today({ r }: { r: BookResult }) {
  const t = useTheme();
  const td = r.today;
  const trendW = td.w[2];
  return (
    <Card title={`Счёт на ${day(td.date)}`} sub={<>Доли после последнего решения ({day(td.latest)}, {td.latest_kind === "rebalance" ? "ребалансировка" : td.latest_kind === "cut" ? "срез" : "к цели"}) и дрейфа цен. Бюджет месяца — доли по бюджету риска на ребалансировке {day(td.decided)}, до предела. Позиции тренда — доля капитала тренд-блока; в капитале счёта — умноженные на его долю.</>}>
      <div className="book-bar" role="img" aria-label={"Доли сейчас: " + SLEEVES.map((s, i) => `${s} ${pct(td.w[i], 0)}`).join(", ")}>
        {td.w.map((w, i) => w > 0.0005 && (
          <i key={i} style={{ width: `${w * 100}%`, background: sleeveColor(t, i) }} title={`${SLEEVES[i]} ${pct(w, 1)}`} />
        ))}
      </div>
      <ul className="book-legend">
        {SLEEVES.map((s, i) => (
          <li key={s}><i style={{ background: sleeveColor(t, i) }} />{s} <b>{pct(td.w[i], 1)}</b>
            <span className="muted"> · бюджет месяца {pct(td.budget[i], 1)}</span></li>
        ))}
      </ul>
      <div className="book-today">
        <div>
          <h4 className="mini-title">Позиции тренда бота</h4>
          <table className="compact">
            <thead><tr><th>Рынок</th><th className="r">в блоке</th><th className="r">в счёте</th></tr></thead>
            <tbody>
              {r.meta.markets.map((m, i) => (
                <tr key={m}><td>{m}</td><td className="r"><V x={td.pos[i]} f={(v) => num(v, 2, true)} /></td>
                  <td className="r"><V x={td.pos[i] * trendW} f={(v) => pct(v, 1, true)} /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h4 className="mini-title">Акции блока{td.picked ? ` (отбор ${day(td.picked)})` : ""}</h4>
          {td.picks.length ? (
            <ul className="chips">{td.picks.map((p) => (
              <li key={p.ticker} className={"chip" + (p.sold || p.status === "exclude" ? " ev-exclude" : p.status === "warn" ? " ev-warn" : "")}
                title={p.name + (p.events.length ? " · " + p.events.map((e) => `${e.date} ${e.kind_title}${e.detail ? " " + e.detail : ""}`).join("; ") : "")}>
                {p.sold || p.status === "exclude" ? "⛔ " : p.status === "warn" ? "⚠ " : ""}{p.ticker}</li>
            ))}</ul>
          ) : <p className="hint">Блок акций — индекс MCFTR, отбора нет.</p>}
          {td.picks.length > 0 && <p className="hint">Поровну на дату отбора, дальше доли плывут с ценами до следующего конца месяца.
            {td.picks.some((p) => p.status !== "ok" || p.sold) && <> ⛔ — <Term k="exchange_event">событие Мосбиржи</Term> «продать» (продана, доля поделена между остальными), ⚠ — «проверить»; наведите на бумагу. Подробно — на странице <a href="#/events">«События»</a>.</>}</p>}
        </div>
      </div>
    </Card>
  );
}

function ScenarioTable({ r }: { r: BookResult }) {
  const [all, setAll] = useState(false);
  const td = r.today;
  const rows = all ? td.scenarios : td.scenarios.slice(0, 10);
  return (
    <Card title="Сценарии на сегодняшних долях" sub={<>Потеря счёта, если сценарий случится сейчас. Минус — потеря, плюс — выигрыш; для окна из многих 5-дневных ходов — худший ход. Предел — {td.limit ? pct(td.limit, 0) : "не задан"}. История учитывается, только когда окно закончилось до даты решения.</>}>
      <TableWrap label="Сценарии">
        <table className="compact">
          <thead><tr><th>Сценарий</th><th className="r">Счёт</th>
            {SLEEVES.slice(0, 3).map((s) => <th key={s} className="r">{s}</th>)}
            {r.meta.markets.map((m) => <th key={m} className="r muted" title="ход рынка в сценарии">{m}</th>)}</tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.label} className={td.limit && s.loss > td.limit + 1e-6 ? "over" : ""}>
                <td>{s.label}<span className="data-tag">{s.kind === "hyp" ? "гипотеза" : `история · ${s.to.slice(0, 4)}`}</span></td>
                <td className="r"><b><V x={-s.loss} f={(v) => pct(v, 1, true)} eps={0.0005} /></b></td>
                {s.sleeves.map((v, i) => <td key={i} className="r"><V x={-v} f={(x) => pct(x, 1, true)} eps={0.0005} /></td>)}
                {s.moves.map((v, i) => <td key={i} className="r muted">{pct(v, 0, true)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      {td.scenarios.length > 10 && (
        <button type="button" className="ghost small" onClick={() => setAll(!all)}>{all ? "первые 10" : `все ${td.scenarios.length}`}</button>
      )}
    </Card>
  );
}

function diffText(name: string, d: SharpeDiff | Record<string, never> | undefined) {
  if (!d || !("diff" in d)) return null;
  return <li key={name}>{name}: {num(d.diff, 2, true)} (t = {num(d.t, 1, true)}, корреляция {num(d.rho, 2)})</li>;
}

function Compare({ r }: { r: BookResult }) {
  const t = useTheme();
  const books = r.rows.filter((x) => x.kind === "book");
  const sleeves = r.rows.filter((x) => x.kind === "sleeve");
  const line = (x: BookRow) => r.series.equity[x.key] && ["book", "no_cap", "6040", "equity:mcftr", "cash"].includes(x.key) || x.key.startsWith("trend:");
  const head = (
    <tr><th>Портфель</th><th className="r">В год</th><th className="r">Вол.</th><th className="r"><Term k="sharpe">Шарп</Term></th>
      <th className="r">Просадка</th><th className="r" title="худшие 4 недели подряд">4 нед.</th>
      <th className="r"><Term k="scenario_cap">Худш. сценарий</Term></th>
      <th className="r" title="средняя доля денег">Деньги</th><th className="r" title="перенос капитала между блоками в год, в одну сторону">Оборот</th></tr>
  );
  const row = (x: BookRow) => (
    <tr key={x.key}>
      <td className="nowrap">{line(x) && <i className="swatch" style={{ background: lineColor(t, x.key) }} aria-hidden="true" />}{x.title}</td>
      <td className="r"><V x={x.cagr} f={(v) => pct(v, 1, true)} /></td>
      <td className="r">{pct(x.vol, 1)}</td>
      <td className="r">{num(x.sharpe, 2)}</td>
      <td className="r">{pct(x.dd, 1)}</td>
      <td className="r"><V x={x.worst_4w} f={(v) => pct(v, 1, true)} /></td>
      <td className={"r" + (x.worst_scenario !== undefined && r.meta.opts.limit && (x.worst_scenario ?? 0) > r.meta.opts.limit + 1e-6 ? " neg" : "")}>
        {x.worst_scenario !== undefined ? pct(x.worst_scenario === null ? null : -x.worst_scenario, 0, true) : ""}</td>
      <td className="r">{x.cash_share !== undefined ? pct(x.cash_share, 0) : ""}</td>
      <td className="r">{x.turnover !== undefined ? pct(x.turnover, 0) : ""}</td>
    </tr>
  );
  const T = r.tests;
  return (
    <Card title="Блоки против простых портфелей" sub="Все строки — на одних и тех же неделях. Варианты меняют одну настройку портфеля. «Худший сценарий» — наибольшая потеря из списка сценариев на долях любой недели (у варианта без предела видно, от чего предел защищает).">
      <TableWrap label="Сравнение">
        <table className="compact">
          <thead>{head}</thead>
          <tbody>
            <tr className="group"><td colSpan={9}>портфель и его варианты</td></tr>
            {books.map(row)}
            <tr className="group"><td colSpan={9}>блоки по отдельности</td></tr>
            {sleeves.map(row)}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Шарп портфеля над деньгами — {num(T.book.sharpe, 2)}, интервал ±2σ — от {num(T.book.low, 2)} до {num(T.book.high, 2)} за {num(T.book.years, 1)} лет (t = {num(T.book.t, 1)}). Разница Шарпов на одних неделях, её t учитывает корреляцию рядов (t больше 2 — разница вряд ли случайна):</p>
      <ul className="foot">
        {diffText("против 60/40", T["6040"])}
        {diffText("против варианта без предела", T.no_cap)}
        {diffText("против индекса вместо отбора", T.index)}
        {diffText("против варианта без тренда", T.no_trend)}
      </ul>
    </Card>
  );
}

function Limits({ r }: { r: BookResult }) {
  const cur = r.meta.opts.limit;
  return (
    <Card title="Цена предела" sub="Тот же портфель с разными пределами потерь в сценарии. На истории 2016–2026 не было ни дефолта, ни месяца закрытой биржи с обвалом облигаций. Поэтому здесь видно только, сколько страховка стоит; её польза — в сценариях, которых не случилось.">
      <TableWrap label="Цена предела">
        <table className="compact">
          <thead><tr><th>Предел</th><th className="r">В год</th><th className="r">Вол.</th><th className="r">Шарп</th><th className="r">Просадка</th>
            <th className="r">Худш. сценарий</th><th className="r">Деньги</th><th className="r">Оборот</th></tr></thead>
          <tbody>
            {r.limits.map((x) => (
              <tr key={x.limit} className={x.limit === cur ? "pick sel" : ""}>
                <td>{x.limit ? pct(x.limit, 0) + " капитала" : "без предела"}</td>
                <td className="r"><V x={x.cagr} f={(v) => pct(v, 1, true)} /></td>
                <td className="r">{pct(x.vol, 1)}</td>
                <td className="r">{num(x.sharpe, 2)}</td>
                <td className="r">{pct(x.dd, 1)}</td>
                <td className="r">{pct(x.worst_scenario === undefined || x.worst_scenario === null ? null : -x.worst_scenario, 0, true)}</td>
                <td className="r">{pct(x.cash_share, 0)}</td>
                <td className="r">{pct(x.turnover, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Card>
  );
}

function stackedArea(t: Theme, dates: string[], layers: { name: string; values: number[]; color: string }[]): Option {
  return {
    ...base(t),
    legend: legend(t, { data: layers.map((l) => l.name) }),
    grid: { left: 8, right: 16, top: legendTop(layers.map((l) => l.name)), bottom: 8, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      formatter: (ps: { seriesName: string; value: [string, number]; color: string }[]) =>
        `<div style="margin-bottom:4px;color:${t.ink3}">${day(ps[0]?.value[0])}</div>` +
        ps.map((p) => `<div style="display:flex;justify-content:space-between;gap:14px"><span><i style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${p.color};margin-right:6px;vertical-align:middle"></i>${p.seriesName}</span><b style="font-weight:500">${pct(p.value[1], 1)}</b></div>`).join(""),
    },
    xAxis: axis(t, { type: "time", splitLine: { show: false } }),
    yAxis: axis(t, { type: "value", min: 0, max: 1, axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => pct(v, 0) } }),
    series: layers.map((l) => ({
      name: l.name, type: "line", stack: "w", showSymbol: false, symbol: "none", data: dates.map((d, i) => [d, l.values[i]]),
      lineStyle: { width: 1, color: t.sheet }, itemStyle: { color: l.color }, areaStyle: { color: l.color, opacity: 0.9 },
    })),
  };
}

function Charts({ r }: { r: BookResult }) {
  const t = useTheme();
  const S = r.series;
  const title = (k: string) => r.rows.find((x) => x.key === k)?.title ?? k;
  const eqKeys = ["book", "no_cap", "6040", "equity:mcftr", Object.keys(S.equity).find((k) => k.startsWith("trend:")) ?? "", "cash"]
    .filter((k) => k && S.equity[k]);
  const eq = useMemo(() => timeLines(t, S.dates, eqKeys.map((k) => ({
    name: title(k), values: S.equity[k], color: lineColor(t, k), width: k === "book" ? 2.5 : 2, dashed: k === "cash", z: k === "book" ? 5 : 2,
  })), { log: true, yFmt: (v) => num(v, 1), tipFmt: (v) => num(v, 2), zoom: true }), [t, r]); // eslint-disable-line react-hooks/exhaustive-deps
  const dd = useMemo(() => timeLines(t, S.dates, Object.keys(S.drawdown).map((k) => ({
    name: title(k), values: S.drawdown[k], color: lineColor(t, k), width: k === "book" ? 2.5 : 2, z: k === "book" ? 5 : 2,
  })), { yFmt: (v) => pct(v, 0), tipFmt: (v) => pct(v, 1), max: 0 }), [t, r]); // eslint-disable-line react-hooks/exhaustive-deps
  const w = useMemo(() => stackedArea(t, S.dates, SLEEVES.map((s, i) => ({ name: s, values: S.weights[i], color: sleeveColor(t, i) }))), [t, r]);
  const worst = useMemo(() => {
    const lines = [{ name: "портфель", values: S.worst.map((v) => -v), color: lineColor(t, "book"), width: 2 }];
    if (S.worst_no_cap) lines.push({ name: "без предела", values: S.worst_no_cap.map((v) => -v), color: lineColor(t, "no_cap"), width: 1.5 });
    const o = timeLines(t, S.dates, lines, { yFmt: (v) => pct(v, 0), tipFmt: (v) => pct(v, 1), max: 0 });
    if (r.meta.opts.limit) {
      o.series[0].markLine = { symbol: "none", silent: true, lineStyle: { color: t.bad, width: 1, type: "dashed" },
        label: { color: t.ink3, fontSize: 11, formatter: `предел −${pct(r.meta.opts.limit, 0)}`, position: "insideStartTop" },
        data: [{ yAxis: -r.meta.opts.limit }] };
    }
    return o;
  }, [t, r]);
  return (
    <>
      <Card title="Рост капитала" sub="Логарифмическая шкала, 1 — начало периода. Тренд бота отдельно — на капитале в деньгах.">
        <Chart option={eq} height={360} label="Рост капитала портфеля из блоков и сравнений" />
      </Card>
      <div className="grid2">
        <Card title="Просадка">
          <Chart option={dd} height={260} label="Просадка портфеля и сравнений" />
        </Card>
        <Card title="Худший сценарий на долях недели" sub="Потеря в худшем сценарии из списка: у портфеля она не ниже предела, без предела — сколько было бы.">
          <Chart option={worst} height={260} label="Худший сценарий во времени" />
        </Card>
      </div>
      <Card title="Доли блоков" sub="После решений каждой недели: ребалансировки в конце месяца, срезов предела и контроля просадки.">
        <Chart option={w} height={280} label="Доли блоков во времени" />
      </Card>
    </>
  );
}

function Years({ r }: { r: BookResult }) {
  const c = r.corr;
  return (
    <div className="grid2">
      <Card title="По годам">
        <TableWrap label="Доходность по годам">
          <table className="compact">
            <thead><tr><th>Год</th><th className="r">Портфель</th><th className="r">60/40</th><th className="r">MCFTR</th><th className="r">Деньги</th></tr></thead>
            <tbody>
              {r.years.map((y) => (
                <tr key={y.year}><td>{y.year}</td>
                  <td className="r"><b><V x={y.book} f={(v) => pct(v, 1, true)} /></b></td>
                  <td className="r"><V x={y["6040"]} f={(v) => pct(v, 1, true)} /></td>
                  <td className="r"><V x={y.mcftr} f={(v) => pct(v, 1, true)} /></td>
                  <td className="r">{pct(y.cash, 1)}</td></tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <p className="foot">Первый и последний годы — неполные.</p>
      </Card>
      <Card title="Корреляция блоков" sub="Недельные доходности за весь период.">
        <TableWrap label="Корреляция">
          <table className="compact">
            <thead><tr><th />{c.labels.map((l) => <th key={l} className="r">{l}</th>)}</tr></thead>
            <tbody>
              {c.labels.map((l, i) => (
                <tr key={l}><td>{l}</td>{c.values[i].map((v, j) => <td key={j} className="r">{i === j ? "—" : num(v, 2, true)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <p className="foot">Тренд бота отрицательно связан с акциями и облигациями: он часто держит юань и золото, когда рублёвые активы падают. Поэтому даже при сильном урезании предел оставляет ему место.</p>
      </Card>
    </div>
  );
}

function cutText(d: BookDecision): string {
  return d.cut.some((c) => c < 0.995) ? d.cut.map((c) => c < 0.995 ? `×${num(c, 2)}` : "—").join(" / ") : "";
}

function Log({ r }: { r: BookResult }) {
  const t = useTheme();
  const [n, setN] = useState(24);
  const [onlyRebal, setOnlyRebal] = useState(false);
  const rows = r.log.filter((x) => !onlyRebal || x.kind === "rebalance");
  return (
    <Card title="Журнал решений" sub="Новые сверху. Ребалансировка — конец месяца: бюджет риска на окне, затем предел по сценариям и контроль просадки. Срез — на долях недели какой-то сценарий забирает больше предела. «К цели» — блок отошёл от цели больше чем на 5 п. п. Худший сценарий — для долей до решения → после него. «Итог» — доходность счёта до следующего решения.">
      <label className="check"><input type="checkbox" checked={onlyRebal} onChange={(e) => setOnlyRebal(e.target.checked)} /> только ребалансировки</label>
      <TableWrap label="Журнал решений">
        <table className="compact">
          <thead><tr><th>Дата</th><th>Решение</th><th>Доли</th>
            <th>Худший сценарий</th><th><Term k="cut">Срез</Term></th><th className="r" title="позиции тренда: юань, золото, MCFTR, ОФЗ — доля капитала блока">Тренд</th>
            <th title="наведите — какие бумаги купить и продать">Отбор</th><th className="r">Итог</th></tr></thead>
          <tbody>
            {rows.slice(0, n).map((d) => (
              <tr key={d.date + d.kind}>
                <td className="nowrap">{day(d.date)}</td>
                <td className="nowrap">{d.kind === "rebalance" ? "ребалансировка" : d.kind === "cut" ? <span className="neg">срез</span> : d.kind === "event" ? <span className="neg">продажа акции</span> : "к цели"}{d.vol !== undefined && d.vol !== null && <span className="muted" title="ожидаемая волатильность долей бюджета, до предела"> · σ {pct(d.vol, 1)}</span>}{d.m < 1 && <span className="muted"> · контроль ×{num(d.m, 2)}</span>}</td>
                <td className="nowrap">
                  <span className="book-mini" aria-label={SLEEVES.map((s, i) => `${s} ${pct(d.w[i], 0)}`).join(", ")}>
                    {d.w.map((w, i) => <i key={i} style={{ width: `${w * 100}%`, background: sleeveColor(t, i) }} />)}
                  </span>
                  <span className="muted"> {d.w.slice(0, 3).map((w) => pct(w, 0)).join(" / ")}</span>
                </td>
                {d.kind === "event" ? <td className="book-scen"><b>{d.name}</b> <span className="muted">{d.ticker}</span> — {d.event} ({pct(d.share, 1)} блока акций), новость {day(d.news)}{d.url && <> · <a href={d.url} target="_blank" rel="noreferrer">биржа</a></>}</td> :
                <td className="book-scen">{d.scenario} <span className="nowrap"><V x={-d.loss_before} f={(v) => pct(v, 0, true)} /> → <V x={-d.loss_after} f={(v) => pct(v, 0, true)} /></span></td>}
                <td className="nowrap">{cutText(d)}</td>
                <td className="r nowrap muted">{d.pos.map((p) => num(p, 1, true)).join(" ")}</td>
                <td className="nowrap">{d.added?.length || d.removed?.length ? (
                  <span title={`купить: ${d.added?.join(", ") || "—"}; продать: ${d.removed?.join(", ") || "—"}`}>
                    <span className="pos">+{d.added?.length ?? 0}</span> <span className="neg">−{d.removed?.length ?? 0}</span>
                  </span>) : ""}</td>
                <td className="r"><V x={d.next} f={(v) => pct(v, 1, true)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      {rows.length > n && <button type="button" className="ghost small" onClick={() => setN(rows.length)}>все {rows.length}</button>}
    </Card>
  );
}
