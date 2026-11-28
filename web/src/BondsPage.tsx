import { useEffect, useMemo, useState } from "react";
import { api, type BondIssue, type BondRow, type BondsResult } from "./api";
import { Chart, timeLines } from "./charts";
import { day, num, pct } from "./format";
import { Guide, Term } from "./help";
import { useTheme } from "./theme";
import { Card, Note, Segmented, TableWrap, V } from "./ui";

const KINDS = ["ofz_short", "ofz_long", "ofz_ladder", "ofz_float", "ofz_linker", "corp_fixed", "corp_float"];
const MIXES = ["near_cash", "ladder", "ofz3", "mixed"];
const BENCH = ["RGBITR", "RUCB", "SBGB", "cash"];
const POLICY = ["base", "policy_rule", "policy"];
const GROUPS: [string, string[]][] = [["Виды облигаций", KINDS], ["Смеси видов", MIXES], ["По режиму ЦБ", POLICY],
  ["Для сравнения", BENCH]];
const REGIMES: Record<string, string> = { tight: "ужесточение", hold: "пауза", ease: "смягчение" };

export function BondsPage() {
  const [res, setRes] = useState<BondsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = () => {
    setBusy(true);
    setError("");
    api.bonds().then(setRes).catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
  };
  useEffect(run, []);

  return (
    <div className="lab">
      <header className="lab-head">
        <h1>Облигации из выпусков</h1>
        <p>Блок облигаций без чужих фондов (кроме фонда денег): ОФЗ с постоянным купоном, <Term k="floater">флоатеры</Term> ОФЗ-ПК, <Term k="linker">линкеры</Term> ОФЗ-ИН и надёжные корпоративные — каждый вид со своей ролью. Каждый месяц вид пересобирается из выпусков Мосбиржи; проверка — неделя за неделей с 2014 года, с купонами и погашениями по графику, налогом с купонов и издержками сделок.</p>
      </header>
      <Guide id="bonds" />
      {error && <Note kind="warn">Не посчиталось: {error}</Note>}
      {!res && busy && <div className="loading"><div className="spinner" /></div>}
      {!res && busy && <p className="hint">Первый расчёт: недельные срезы облигаций Мосбиржи с 2011 года (если их ещё нет — минут двадцать) и графики выплат.</p>}
      {res && (
        <div className={busy ? "stale" : ""}>
          <Summary r={res} />
          <Policy r={res} />
          <Growth r={res} />
          <Years r={res} />
          <Today r={res} />
          {res.notes.length > 0 && <Note>{res.notes.map((n) => <div key={n}>{n}</div>)}</Note>}
        </div>
      )}
    </div>
  );
}

function Summary({ r }: { r: BondsResult }) {
  const by = Object.fromEntries(r.rows.map((x) => [x.key, x]));
  const cell = (x: number | undefined, sign = false) => <V x={x} f={(v) => pct(v, 1, sign)} />;
  const row = (x: BondRow) => (
    <tr key={x.key}>
      <td>{x.title}</td>
      <td className="r muted nowrap">{day(x.from)}</td>
      <td className="r">{cell(x.whole.cagr)}</td>
      <td className="r">{x.whole_tax ? cell(x.whole_tax.cagr) : "—"}</td>
      <td className="r">{pct(x.whole.vol, 1)}</td>
      <td className="r">{cell(x.whole.dd === undefined ? undefined : -x.whole.dd)}</td>
      <td className="r">{num(x.whole.sharpe, 2)}</td>
      <td className="r">{cell(x.recent.cagr)}</td>
      <td className="r">{x.recent_tax ? cell(x.recent_tax.cagr) : "—"}</td>
      <td className="r">{cell(x.recent.dd === undefined ? undefined : -x.recent.dd)}</td>
      <td className="r muted">{x.issues === null ? "" : num(x.issues, 0)}</td>
    </tr>
  );
  return (
    <Card title="Виды облигаций против индексов и фонда" sub={<>С начала проверки ({day(r.start)}) или со дня, когда у вида появились ликвидные выпуски, и за пять лет с {day(r.recent_from)}. «После налога» — с <Term k="coupon_tax">налогом {pct(r.tax, 0)} с купонов</Term>; «до налога» — доход на ИИС с освобождением. У индексов и фонда налога внутри нет: фонд платит его только при продаже паёв.</>}>
      <TableWrap label="Виды облигаций">
        <table className="compact">
          <thead>
            <tr><th rowSpan={2}>Что</th><th className="r" rowSpan={2}>С</th><th className="c" colSpan={5}>Вся проверка</th><th className="c" colSpan={3}>Пять лет</th><th className="r" rowSpan={2} title="выпусков в виде в среднем">Бумаг</th></tr>
            <tr><th className="r">в год</th><th className="r">после налога</th><th className="r">волат.</th><th className="r"><Term k="dd">просадка</Term></th><th className="r">Шарп</th>
              <th className="r">в год</th><th className="r">после налога</th><th className="r">просадка</th></tr>
          </thead>
          {GROUPS.map(([title, keys]) => (
            <tbody key={title}>
              <tr className="group"><td colSpan={11}>{title}</td></tr>
              {keys.filter((k) => by[k]).map((k) => row(by[k]))}
            </tbody>
          ))}
        </table>
      </TableWrap>
      <p className="foot">Шарп — сверх RUONIA. Смеси — доли видов, постоянные: «Почти деньги» — флоатеры ОФЗ-ПК 70% и короткие ОФЗ 30%; «ОФЗ трёх видов» — лестница 50%, флоатеры и линкеры по 25%; «ОФЗ и корпоративные» — лестница 30%, флоатеры и линкеры по 15%, корпоративные с постоянным купоном 25% и флоатеры 15%. Пока у вида нет выпусков, его доля у остальных.</p>
    </Card>
  );
}

function Policy({ r }: { r: BondsResult }) {
  const p = r.policy;
  const kinds = Array.from(new Set([...Object.keys(p.base), ...Object.values(p.priors).flatMap((x) => Object.keys(x)),
    ...Object.keys(p.mix)])).sort((a, b) => KINDS.indexOf(a) - KINDS.indexOf(b));
  const changes = p.history.filter((h, i) => i === 0 || p.history[i - 1].regime !== h.regime);
  const cell = (x: number | undefined) => (x ? pct(x, 0) : "");
  return (
    <Card title={`Режим ЦБ сейчас: ${p.title}`} sub={<>С {day(p.since)}, ключевая ставка {pct(p.key, 2)}. Режим — по ставке за последние {p.params.weeks} недель: подняли и не снижали — ужесточение, снизили и не поднимали — смягчение, не меняли — пауза. Доли «заранее» заданы до проверки; «оптимум» — каждый месяц лучшее сочетание доходности и колебаний на прошлых месяцах того же режима (после налога), наполовину назад к долям «заранее» — иначе десять циклов ставки переобучили бы его.</>}>
      <TableWrap label="Доли видов по режимам">
        <table className="compact">
          <thead><tr><th>Вид</th><th className="r">База</th>{Object.keys(p.priors).map((g) => <th key={g} className="r">{REGIMES[g]}: заранее</th>)}<th className="r">Сейчас: оптимум</th></tr></thead>
          <tbody>
            {kinds.map((k) => (
              <tr key={k}><td>{r.titles[k] ?? k}</td><td className="r">{cell(p.base[k])}</td>
                {Object.keys(p.priors).map((g) => <td key={g} className={"r" + (g === p.regime ? " sel" : "")}>{cell(p.priors[g][k])}</td>)}
                <td className="r"><b>{cell(p.mix[k])}</b></td></tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Смены режима: {changes.map((h) => `${day(h.date)} — ${REGIMES[h.regime]}${h.key !== null ? ` (${pct(h.key, 2)})` : ""}`).join("; ")}.</p>
      <TableWrap label="Выпуски плана">
        <table className="compact">
          <thead><tr><th>Выпуск</th><th>Вид</th><th className="r">Доля блока</th><th className="r">Цена, %</th><th className="r">Доходность</th><th className="r">Дюрация</th></tr></thead>
          <tbody>
            {p.plan.map((b) => (
              <tr key={`${b.kind}-${b.secid}`}><td>{b.name} <span className="muted">{b.secid}</span></td><td className="muted">{SHORT[b.kind] ?? b.kind}</td>
                <td className="r">{pct(b.weight, 1)}</td><td className="r">{num(b.price, 2)}</td><td className="r">{pct(b.ytm, 1)}</td><td className="r">{num(b.duration, 1)}</td></tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Выпуски плана счёта («Мой счёт», бот): не больше 15 по долям видов — у лестницы разные сроки, у остальных видов первые по ликвидности или доходу; выпуск двух видов — одна строка. Всего в составе видов {p.issues.length} выпусков.</p>
    </Card>
  );
}

function Growth({ r }: { r: BondsResult }) {
  const t = useTheme();
  const [view, setView] = useState<"mix" | "kinds">("mix");
  const [taxed, setTaxed] = useState(false);
  const keys = view === "mix" ? ["policy", "base", "near_cash", "ladder", "RGBITR", "RUCB", "SBGB", "cash"] : [...KINDS, "cash"];
  const opt = useMemo(() => {
    const lines = keys.filter((k) => r.curves.series[k]).map((k, i) => {
      const tk = taxed && r.curves.series[`${k}:tax`] ? `${k}:tax` : k;
      return { name: r.titles[k] ?? k, values: r.curves.series[tk], color: k === "cash" ? t.gray : t.series[i % 8],
        dashed: k === "cash" || BENCH.includes(k), width: k === "policy" ? 3 : MIXES.includes(k) ? 2.5 : 2 };
    });
    const all = lines.flatMap((l) => l.values.filter((v): v is number => v !== null));
    return timeLines(t, r.curves.dates, lines, { log: true, yFmt: (v) => num(v, 1), tipFmt: (v) => num(v, 2), zoom: true,
      min: Math.floor(Math.min(...all) * 10) / 10, max: Math.ceil(Math.max(...all) * 2) / 2 });
  }, [t, r, view, taxed]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Card title="Рост рубля" sub="Каждая линия — с одного рубля в день своего начала (фонд SBGB — с 2019 года, флоатеры и линкеры — с 2015-го). Логарифмическая шкала: одинаковый наклон — одинаковый процент в год. Пунктир — индексы, фонд и деньги.">
      <div className="lab-controls">
        <Segmented label="Что показать" value={view} onChange={setView}
          options={[{ value: "mix", label: "смеси и индексы" }, { value: "kinds", label: "виды облигаций" }]} />
        <Segmented label="Налог" value={taxed ? 1 : 0} onChange={(v) => setTaxed(v === 1)}
          options={[{ value: 0, label: "до налога" }, { value: 1, label: `после налога ${pct(r.tax, 0)}` }]} />
      </div>
      <Chart option={opt} height={380} label="Рост рубля в облигациях" />
    </Card>
  );
}

function Years({ r }: { r: BondsResult }) {
  const keys = [...KINDS, ...MIXES, ...POLICY, ...BENCH].filter((k) => r.rows.some((x) => x.key === k));
  return (
    <Card title="По годам" sub="Доход за календарный год до налога.">
      <TableWrap label="Доход по годам">
        <table className="compact">
          <thead><tr><th>Год</th>{keys.map((k) => <th key={k} className="r" title={r.titles[k]}>{SHORT[k] ?? k}</th>)}</tr></thead>
          <tbody>
            {r.years.map((y) => (
              <tr key={y.year}><td>{y.year}</td>{keys.map((k) => <td key={k} className="r">
                {typeof y[k] === "number" ? <V x={y[k] as number} f={(v) => pct(v, 1, true)} /> : ""}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Card>
  );
}

const SHORT: Record<string, string> = {
  ofz_short: "ОФЗ коротк.", ofz_long: "ОФЗ длин.", ofz_ladder: "лестница", ofz_float: "ОФЗ-ПК", ofz_linker: "ОФЗ-ИН",
  corp_fixed: "корп.", corp_float: "корп. флоат.", near_cash: "смесь: почти деньги", ladder: "смесь: лестница",
  base: "база", policy_rule: "ЦБ: заранее", policy: "ЦБ: оптимум", ofz3: "смесь: ОФЗ×3", mixed: "смесь: с корп.",
  RGBITR: "RGBITR", RUCB: "RUCB", SBGB: "SBGB", cash: "RUONIA",
};

function Today({ r }: { r: BondsResult }) {
  const [kind, setKind] = useState("ofz_ladder");
  const items: BondIssue[] = r.today[kind] ?? [];
  const float = kind === "corp_float";
  return (
    <Card title={`Состав на ${day(r.date)}`} sub={<>Что вид держал бы сегодня — выпуски поровну. Корпоративные сегодня — только с риском брокера 1 (список T-Invest из server-analytic-system). <Term k="g_spread">Спред</Term> — доходность сверх <Term k="kbd">КБД</Term> на ту же дюрацию; у флоатера вместо него — надбавка текущего купона к ключевой ставке.</>}>
      <div className="lab-controls">
        <label className="field"><span>Вид</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => <option key={k} value={k}>{r.titles[k]} — {r.today[k]?.length ?? 0}</option>)}
          </select>
        </label>
      </div>
      {items.length === 0 ? <p className="hint">Сегодня ни один выпуск этого вида не проходит отбор.</p> : (
        <TableWrap label="Состав вида">
          <table className="compact">
            <thead><tr><th>Код</th><th>Выпуск</th><th className="r">Цена, %</th><th className="r">Доходность</th>
              <th className="r"><Term k="duration">Дюрация</Term>, лет</th><th className="r">{float ? "Надбавка" : "Спред"}</th>
              <th className="r">До погашения или <Term k="offer">оферты</Term>, лет</th><th className="r">Оборот за 4 нед.</th></tr></thead>
            <tbody>
              {items.map((b) => (
                <tr key={b.secid}>
                  <td className="nowrap">{b.secid}</td><td>{b.name}</td><td className="r">{num(b.price, 2)}</td>
                  <td className="r">{pct(b.ytm, 1)}</td><td className="r">{num(b.duration, 1)}</td>
                  <td className="r">{(float ? b.margin : b.spread) === null ? "—" : pct(float ? b.margin : b.spread, 2, true)}</td><td className="r">{num(b.life, 1)}</td>
                  <td className="r muted">{num(b.value4 / 1e6, 0)} млн ₽</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <p className="foot">Отбор: торги не меньше чем в 3 из 4 последних недель и в среднем от {num(r.params.min_value / 1e3, 0)} тыс. ₽ в неделю, цена от 85% номинала, до погашения или оферты не меньше {num(r.params.buy_life, 1)} года (продажа — когда меньше {num(r.params.sell_life, 2)}). ОФЗ — до {r.params.max_ofz} самых ликвидных; корпоративные — до {r.params.max_corp}, один выпуск на эмитента: спред в нижней половине рынка и не выше {pct(r.params.spread_cap, 0)}, флоатер — надбавка не выше {pct(r.params.float_margin, 1)}.</p>
    </Card>
  );
}
