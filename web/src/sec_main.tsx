import { useMemo, useState } from "react";
import type { Perf, StudyResult } from "./api";
import { bars, Chart, heat, timeLines } from "./charts";
import { day, month, num, pct, years } from "./format";
import { slotColor, useTheme } from "./theme";
import { AssetName, Card, Note, Segmented, TableWrap, Tile, V } from "./ui";

type P = { r: StudyResult; slots: number[] };

export function Summary({ r }: P) {
  const b = r.rule.book, h = r.rule.hold;
  const per = r.meta.period;
  const pf = r.meta.mode === "portfolio";
  return (
    <div className="summary">
      <div className="tiles">
        <Tile label={pf ? "Портфель: в год" : "Правило: в год"} value={pct(b.cagr, 1, true)} toneClass={b.cagr >= 0 ? "pos" : "neg"}
          sub={<>{r.meta.bench}: {pct(h.cagr, 1, true)}</>} />
        <Tile label="Шарп" value={num(b.sharpe, 2)} sub={<>{r.meta.bench}: {num(h.sharpe, 2)}</>} />
        <Tile label="Просадка" value={pct(b.dd, 1)} sub={<>{day(b.dd_from)} – {day(b.dd_to)}</>} />
        <Tile label="Волатильность" value={pct(b.vol, 1)} sub={<>худший день {pct(b.worst_day, 1)}</>} />
        <Tile label="Худший год" value={pct(b.worst_year, 1)} sub={<>скользящие {Math.round(r.meta.ppy)} дн.</>} />
      </div>
      <p className="period">
        {day(per.from)} – {day(per.to)}, {years(per.years)} · {per.mode === "common" ? "общий период активов" : "с начала каждого актива"} ·
        {pf ? "портфель с заданными весами" : <>риск {pct(r.meta.params.risk, 1)} на актив · окно {r.meta.params.lookbacks.join("+")}</>} · {r.meta.control.name} ·
        расчёт {num(r.meta.elapsed, 1)} с
      </p>
      {r.meta.warnings.length > 0 && (
        <details className="warnings">
          <summary>Замечания к данным: {r.meta.warnings.length}</summary>
          <ul>{r.meta.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

export function Overview({ r, slots }: P) {
  const t = useTheme();
  const pf = r.meta.mode === "portfolio";
  const [corrMode, setCorrMode] = useState<"full" | "last_year">("full");
  const o = r.overview;
  const curves = useMemo(() => timeLines(t, o.curves.dates, o.curves.values.map((v, j) => ({
    name: r.meta.labels[j], values: v, color: slotColor(t, slots[j]) })), {
    log: true, zoom: true, yFmt: (v) => num(v, v < 10 ? 1 : 0), tipFmt: (v) => num(v, 2),
  }), [t, o, r.meta.labels, slots]);
  const corr = useMemo(() => heat(t, o.corr.labels, o.corr.labels, o.corr[corrMode], { range: 1 }), [t, o, corrMode]);
  return (
    <>
      <Card title="Активы" sub="Доходность сверх стоимости удержания (что зарабатывает лонг, профинансированный по ставке). Хвосты — по всей истории актива.">
        <TableWrap label="Активы">
          <table>
            <thead><tr>
              <th>Актив</th><th>Источник</th><th>Лонг платит</th><th>История</th><th className="r">В год</th><th className="r">Вол.</th><th className="r">Шарп</th>
              <th className="r">Просадка</th><th className="r" title="индекс хвоста падений, GPD">ξ падений</th><th className="r">ξ роста</th>
              <th className="r">Эксцесс</th><th className="r">Вол. сейчас</th>
              {pf ? <th className="r" title="доля капитала сегодня (веса приведены к 100% по бумагам на бирже)">Вес</th> : <>
                <th className="r" title="сила тренда сейчас, с пределом шорта">Сила</th>
                <th className="r" title="номинал полной позиции при выбранном риске, доля капитала">Полная поз.</th></>}
            </tr></thead>
            <tbody>
              {o.assets.map((a, j) => {
                const info = r.meta.assets[j];
                return (
                  <tr key={j}>
                    <td><AssetName label={a.label} slot={slots[j]} /></td>
                    <td className="muted nowrap">{shortSource(info.source)}</td>
                    <td className="muted nowrap">{info.carry === "none" ? "–" : carryName(info.carry) + (info.carry_offset ? " " + pct(info.carry_offset, 1, true) : "")}</td>
                    <td className="muted nowrap">{day(a.first)} – {day(a.last)}</td>
                    <td className="r"><V x={a.cagr} f={(x) => pct(x, 1, true)} /></td>
                    <td className="r">{pct(a.vol, 0)}</td>
                    <td className="r">{num(a.sharpe, 2)}</td>
                    <td className="r">{pct(a.dd, 0)}</td>
                    <td className="r">{num(a.xi_down, 2)}</td>
                    <td className="r">{num(a.xi_up, 2)}</td>
                    <td className="r">{num(a.kurt, 1)}</td>
                    <td className="r">{pct(a.vol_now, 0)}</td>
                    {pf ? <td className="r">{pct(a.full_now, 1)}</td> : <>
                      <td className="r"><V x={a.w_now} f={(x) => num(x, 2, true)} /></td>
                      <td className="r">{num(a.full_now, 2)}</td></>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
        <p className="foot">ξ &gt; 0 — толстый хвост (0,25 и больше — нет четвёртого момента). {pf ? "Вес — доля капитала в портфеле сегодня." : "«Сила» — clip(z) правила на последний день: +1 — полный лонг, −1 — полный шорт."}</p>
      </Card>
      <Card title="Индексы избыточной доходности" sub="Логарифмическая шкала, 1 = начало периода. Колесо мыши и ползунок — масштаб.">
        <Chart option={curves} height={360} label="Индексы избыточной доходности активов" />
      </Card>
      {o.corr.labels.length > 1 && (
        <Card title="Корреляции недельных доходностей">
          <Segmented value={corrMode} onChange={setCorrMode} label="Период корреляций"
            options={[{ value: "full", label: "весь период" }, { value: "last_year", label: "последние 52 недели" }]} />
          <Chart option={corr} height={Math.max(220, 46 * o.corr.labels.length + 60)} label="Матрица корреляций" />
        </Card>
      )}
    </>
  );
}

function shortSource(s: string): string {
  return ({ "Yahoo Finance": "Yahoo", "Мосбиржа ISS": "Мосбиржа", "Банк России": "ЦБ" } as Record<string, string>)[s] ?? s;
}

export function carryName(c: string): string {
  return ({ rub: "RUONIA", usd: "T-bill", "rub-usd": "RUONIA − T-bill", fixed: "фикс.", none: "ничего" } as Record<string, string>)[c] ?? c;
}

const PERF_ROWS: [string, keyof Perf, (x: number) => string][] = [
  ["В год (CAGR)", "cagr", (x) => pct(x, 1, true)],
  ["Волатильность", "vol", (x) => pct(x, 1)],
  ["Шарп", "sharpe", (x) => num(x, 2)],
  ["Максимальная просадка", "dd", (x) => pct(x, 1)],
  ["Calmar (доход / просадка)", "calmar", (x) => num(x, 2)],
  ["Худший день", "worst_day", (x) => pct(x, 1)],
  ["Худший месяц", "worst_month", (x) => pct(x, 1)],
  ["Худший год (скользящий)", "worst_year", (x) => pct(x, 1)],
  ["Лучший год", "best_year", (x) => pct(x, 1, true)],
  ["Дольше всего под водой, лет", "underwater", (x) => num(x, 1)],
  ["Асимметрия дня", "skew", (x) => num(x, 2)],
  ["Эксцесс дня", "kurt", (x) => num(x, 1)],
];

export function Rule({ r, slots }: P) {
  const t = useTheme();
  const R = r.rule;
  const pf = r.meta.mode === "portfolio";
  const main = pf ? "портфель" : "правило", bench = r.meta.bench;
  const [heatMode, setHeatMode] = useState<"sharpe" | "mean">("sharpe");
  const eq = useMemo(() => timeLines(t, R.equity.dates, [
    { name: pf ? "портфель с заданными весами" : "правило тренда", values: R.equity.values[0], color: t.series[0] },
    { name: pf ? "те же бумаги поровну" : "держать с размером по волатильности", values: R.equity.values[1], color: t.gray },
  ], { log: true, zoom: true, yFmt: (v) => num(v, v < 10 ? 1 : 0), tipFmt: (v) => num(v, 2) }), [t, R, pf]);
  const dd = useMemo(() => timeLines(t, R.equity.dates, [
    { name: main, values: R.equity.values[2], color: t.series[0], area: true },
    { name: bench, values: R.equity.values[3], color: t.gray },
  ], { yFmt: (v) => pct(v, 0), tipFmt: (v) => pct(v, 1), max: 0 }), [t, R, main, bench]);
  const yearBars = useMemo(() => bars(t, R.years.map((y) => y.year), [
    { name: main, values: R.years.map((y) => y.book), color: t.series[0] },
    { name: bench, values: R.years.map((y) => y.hold), color: t.gray },
  ]), [t, R, main, bench]);
  const H = R.lookbacks;
  const heatOpt = useMemo(() => heat(t, H.columns, H.rows, H[heatMode], {
    fmt: heatMode === "sharpe" ? (v) => num(v, 2) : (v) => pct(v, 1), range: heatMode === "sharpe" ? 1.2 : undefined,
  }), [t, H, heatMode]);
  const n = r.meta.labels.length;
  const pos = useMemo(() => timeLines(t, R.positions.dates, R.positions.values.slice(0, n).map((v, j) => ({
    name: r.meta.labels[j], values: v, color: slotColor(t, slots[j]), width: 1.5 })), {
    yFmt: (v) => num(v, 1), tipFmt: (v) => num(v, 2), zoom: true,
  }), [t, R, n, r.meta.labels, slots]);
  const mult = R.positions.values[n];
  const hasControl = mult?.some((v) => v !== null && v < 1);
  const multOpt = useMemo(() => timeLines(t, R.positions.dates, [{ name: "множитель размера", values: mult, color: t.series[6], area: true }],
    { yFmt: (v) => num(v, 2), min: 0, max: 1 }), [t, R, mult]);

  return (
    <>
      <Card title={pf ? "Портфель против «поровну»" : "Правило против «держать»"} sub={<>{pf
        ? "«Поровну» — те же бумаги равными долями (тоже с перенормировкой на бумаги, которые уже торгуются). Веса выбраны сегодня, так что прошлое здесь — проверка на прочность, а не оценка доходности."
        : "«Держать» — всегда полный лонг с тем же размером по волатильности и тем же ГО."} Разница доходностей по неделям: t = {num(R.vs_hold_t, 1)}.</>}>
        <div className="two">
          <TableWrap label="Сравнение">
            <table>
              <thead><tr><th></th><th className="r">{pf ? "Портфель" : "Правило"}</th><th className="r">{pf ? "Поровну" : "Держать"}</th></tr></thead>
              <tbody>
                {PERF_ROWS.map(([name, k, f]) => (
                  <tr key={k}><td>{name}</td><td className="r">{f(R.book[k] as number)}</td><td className="r">{f(R.hold[k] as number)}</td></tr>
                ))}
                <tr><td>Оборот, номиналов в год</td><td className="r">{num(R.turnover, 1)}</td><td className="r">–</td></tr>
                <tr><td>Издержки в год</td><td className="r">{pct(R.costs_year, 2)}</td><td className="r">–</td></tr>
              </tbody>
            </table>
          </TableWrap>
          <div>
            <Chart option={eq} height={300} label={pf ? "Капитал портфеля и равных долей, логарифмическая шкала" : "Капитал правила и держателя, логарифмическая шкала"} />
            <Chart option={dd} height={170} label="Просадка от пика" />
          </div>
        </div>
      </Card>

      <Card title="Окна тренда по активам" sub={(pf ? "Для сравнения — правило тренда бота на каждой бумаге. " : "") + "Каждый актив торгуется правилом отдельно (без предела ГО). Строка «вся корзина» — сумма. Подбирать окно по этой таблице — перебор: смотрите на устойчивость по соседним окнам, а не на максимум."}>
        <Segmented value={heatMode} onChange={setHeatMode} label="Показатель"
          options={[{ value: "sharpe", label: "Шарп" }, { value: "mean", label: "средний доход в год" }]} />
        <Chart option={heatOpt} height={Math.max(200, 34 * H.rows.length + 60)} label="Шарп правила по окнам тренда и активам" />
        <p className="foot">Сейчас выбрано окно {H.current}. Синий — плюс, красный — минус.</p>
      </Card>

      <Card title="По годам">
        <Chart option={yearBars} height={260} label="Доходность по календарным годам" />
        <TableWrap label="Вклад активов по годам">
          <table className="compact">
            <thead><tr><th>Год</th><th className="r">{pf ? "Портфель" : "Правило"}</th><th className="r">{pf ? "Поровну" : "Держать"}</th>
              {r.meta.labels.map((l, j) => <th key={j} className="r"><AssetName label={l} slot={slots[j]} /></th>)}
              <th className="r">Издержки</th></tr></thead>
            <tbody>
              {R.years.slice().reverse().map((y) => (
                <tr key={y.year}>
                  <td>{y.year}</td><td className="r"><V x={y.book} f={(x) => pct(x, 1, true)} /></td>
                  <td className="r"><V x={y.hold} f={(x) => pct(x, 1, true)} /></td>
                  {y.assets.map((v, j) => <td key={j} className="r"><V x={v} f={(x) => pct(x, 1, true)} eps={0.0005} /></td>)}
                  <td className="r muted">{pct(-y.costs, 2)}</td>
                </tr>
              ))}
              <tr className="total"><td>в среднем за год</td><td className="r">{pct(R.book.mean, 1, true)}</td><td className="r">{pct(R.hold.mean, 1, true)}</td>
                {R.per_asset_year.map((v, j) => <td key={j} className="r"><V x={v} f={(x) => pct(x, 1, true)} /></td>)}<td className="r muted">{pct(-R.costs_year, 2)}</td></tr>
            </tbody>
          </table>
        </TableWrap>
        <p className="foot">Вклад актива — сумма его дневных доходов за год (без сложного процента), за вычетом его издержек.</p>
      </Card>

      <Card title={pf ? "Веса" : "Позиции"} sub={pf ? "Доля капитала в каждой бумаге: появление новой бумаги уменьшает остальные." : "Номинал позиции, доля капитала: плюс — лонг, минус — шорт."}>
        <Chart option={pos} height={300} label={pf ? "Веса портфеля во времени" : "Позиции правила во времени"} />
        {hasControl && <Chart option={multOpt} height={150} label="Множитель контроля просадки" />}
      </Card>

      <Card title="Худшие дни и месяцы">
        <div className="two">
          <TableWrap label="Худшие дни">
            <table className="compact">
              <thead><tr><th>День</th><th className="r">Счёт</th>{r.meta.labels.map((l, j) => <th key={j} className="r"><AssetName label={l} slot={slots[j]} /></th>)}</tr></thead>
              <tbody>{R.worst_days.map((d) => (
                <tr key={d.date}><td className="nowrap">{day(d.date)}</td><td className="r neg">{pct(d.r, 1)}</td>
                  {d.assets.map((v, j) => <td key={j} className="r"><V x={v} f={(x) => pct(x, 1)} eps={0.0005} /></td>)}</tr>
              ))}</tbody>
            </table>
          </TableWrap>
          <TableWrap label="Худшие месяцы">
            <table className="compact">
              <thead><tr><th>Месяц</th><th className="r">Счёт</th></tr></thead>
              <tbody>{R.worst_months.map((m) => <tr key={m.month}><td>{month(m.month)}</td><td className="r neg">{pct(m.r, 1)}</td></tr>)}</tbody>
            </table>
          </TableWrap>
        </div>
      </Card>
      {pf
        ? <Note>Портфель держит у каждой бумаги её вес капитала каждый день (перебалансировка бесплатна, издержки — только на изменении весов). Доходность — сверх стоимости удержания, у акций Мосбиржи — с дивидендами T-Invest с 2019 года.</Note>
        : <Note>Правило — дневной тренд торгового бота: z = ln(P/P<sub>−L</sub>) / (σ√L), позиция clip(z) × риск / σ, полоса четверть полной позиции, размер от max(волатильности 60 и 20 дней). Подробно — на странице «Теория».</Note>}
    </>
  );
}
