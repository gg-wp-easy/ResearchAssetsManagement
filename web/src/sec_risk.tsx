import { Fragment, useEffect, useMemo, useState } from "react";
import type { N, StudyResult, TailNumbers } from "./api";
import { axis, bars, base, Chart, legend, type Option } from "./charts";
import { day, isNum, num, pct } from "./format";
import { slotColor, useTheme } from "./theme";
import { AssetName, Card, Note, Segmented, TableWrap, V } from "./ui";

type P = { r: StudyResult; slots: number[] };

export function Crises({ r, slots }: P) {
  const [region, setRegion] = useState<"all" | "ru" | "world">("all");
  const rows = r.crises.filter((c) => region === "all" || c.region === region || c.region === "both");
  return (
    <>
      <Card title="Кризисные окна" sub="Что сделали правило и сами активы в известных кризисах. Позиции на входе — номинал, доля капитала, перед первым днём окна.">
        <Segmented value={region} onChange={setRegion} label="Регион"
          options={[{ value: "all", label: "все" }, { value: "ru", label: "Россия" }, { value: "world", label: "мир" }]} />
        <TableWrap label="Кризисные окна">
          <table className="compact">
            <thead>
              <tr><th>Окно</th><th>Даты</th><th className="r">Счёт</th><th className="r">Худший день</th>
                {r.meta.labels.map((l, j) => <th key={j} className="r"><AssetName label={l} slot={slots[j]} /></th>)}</tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.label}>
                  <td>{c.label}</td>
                  <td className="muted nowrap">{day(c.from)} – {day(c.to)}</td>
                  <td className="r">{c.traded ? <V x={c.book} f={(x) => pct(x, 1, true)} /> : <span className="muted" title="до начала периода статистики">–</span>}</td>
                  <td className="r">{c.traded ? <V x={c.worst_day} f={(x) => pct(x, 1)} /> : ""}</td>
                  {c.moves.map((m, j) => (
                    <td key={j} className="r">
                      <V x={m} f={(x) => pct(x, 1, true)} />
                      {c.positions && isNum(c.positions[j]) && c.positions[j] !== 0 && (
                        <span className="pos-in" title="позиция на входе">{num(c.positions[j], 2, true)}</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <p className="foot">{r.meta.mode === "portfolio"
          ? "В ячейке актива — его движение за окно (избыточная доходность) и мелко — вес на входе. Пустая ячейка — бумаги ещё не было на бирже, её вес был у остальных."
          : "В ячейке актива — его движение за окно (избыточная доходность) и мелко — позиция правила на входе. Тренд держит направление кризиса, если оно уже началось; больно — когда разворот приходит сразу."}</p>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------------------- scenarios

interface Book { name: string; kind: "rule" | "worst"; notional: number[] }

function capped(v: number[], go: number[], cap: number): number[] {
  const used = v.reduce((s, x, j) => s + Math.abs(x) * go[j], 0);
  return cap > 0 && used > cap ? v.map((x) => (x * cap) / used) : v;
}

function loss(book: Book, moves: N[][]): number {
  let worst = Infinity;
  for (const mv of moves) {
    const m = mv.map((x) => (isNum(x) ? x : 0));
    const pnl = book.kind === "rule"
      ? book.notional.reduce((s, w, j) => s + w * m[j], 0)
      : -book.notional.reduce((s, w, j) => s + Math.abs(w) * Math.abs(m[j]), 0);
    worst = Math.min(worst, pnl);
  }
  return worst === Infinity ? 0 : worst;
}

function severity(moneyLoss: number): { cls: string; tag: string } {
  if (moneyLoss <= -1) return { cls: "sev-4", tag: "ниже нуля" };
  if (moneyLoss <= -0.6) return { cls: "sev-3", tag: "тяжело" };
  if (moneyLoss <= -0.3) return { cls: "sev-2", tag: "" };
  return { cls: "", tag: "" };
}

export function Scenarios({ r, slots }: P) {
  const S = r.scenarios;
  const n = r.meta.labels.length;
  const pf = r.meta.mode === "portfolio";
  const [risk, setRisk] = useState(S.risk);
  const [hyp, setHyp] = useState(() => S.hypothetical.map((h) => ({ label: h.label, moves: h.moves.map((m) => m * 100) })));
  useEffect(() => { setHyp(S.hypothetical.map((h) => ({ label: h.label, moves: h.moves.map((m) => m * 100) }))); setRisk(S.risk); }, [S]);
  const ms = S.money_share;
  const books: Book[] = useMemo(() => {
    const k = risk / S.risk;
    const full = S.full.map((f) => (isNum(f) ? f * k : 0));
    return [
      { name: pf ? "позиции портфеля" : "позиции правила", kind: "rule", notional: capped(full.map((f, j) => f * S.weights[j]), S.go, S.margin_cap) },
      ...(pf ? [] : [{ name: "худший знак", kind: "worst" as const, notional: capped(full, S.go, S.margin_cap) }]),
    ];
  }, [risk, S, pf]);
  const six: N[] = S.sigma_day.map((s) => (isNum(s) ? 6 * s : null));
  const groups: { title: string; rows: { label: string; moves: N[][]; sixSigma?: boolean }[] }[] = [
    { title: "исторические совместные движения", rows: S.historical },
    { title: "придуманные гэпы, выхода нет", rows: hyp.map((h) => ({ label: h.label, moves: [h.moves.map((m) => m / 100)] })) },
    { title: "шесть дневных сигм против каждой позиции", rows: [{ label: "6σ за день против", moves: [six], sixSigma: true }] },
  ];
  const cell = (b: Book, row: { moves: N[][]; sixSigma?: boolean }) => {
    const v = row.sixSigma ? -b.notional.reduce((s, w, j) => s + Math.abs(w) * (six[j] ?? 0), 0) : loss(b, row.moves);
    const money = pf ? v : v / ms;
    const sev = severity(money);
    return (
      <td className={"r nowrap " + sev.cls}>
        <V x={v} f={(x) => pct(x, 1, true)} eps={0.0005} />{!pf && <> <span className="muted">({pct(money, 0, true)})</span></>}
        {sev.tag && <span className="sev-tag">{sev.tag === "ниже нуля" ? "⛔ " : "⚠ "}{sev.tag}</span>}
      </td>
    );
  };
  return (
    <>
      <Card title={pf ? "Сегодняшние веса" : "Сегодняшние позиции"} sub={pf
        ? <>Веса на {day(S.date)}, доля капитала; σ дня — по волатильности последних месяцев.</>
        : <>Размер — от волатильности на {day(S.date)}: спокойный рынок даёт большие позиции, и тот же шок стоит дороже. Предел ГО — {pct(S.margin_cap, 0)} капитала.</>}>
        <TableWrap label="Позиции">
          <table className="compact">
            <thead><tr><th>Актив</th><th className="r">Вол. сейчас</th><th className="r">σ дня</th>
              {pf ? <th className="r">Вес</th> : <><th className="r">Полная позиция</th>
                <th className="r">Сила правила</th><th className="r">Позиция правила</th><th className="r">ГО</th></>}</tr></thead>
            <tbody>{r.meta.labels.map((l, j) => (
              <tr key={j}><td><AssetName label={l} slot={slots[j]} /></td><td className="r">{pct(S.vol_now[j], 0)}</td>
                <td className="r">{pct(S.sigma_day[j], 2)}</td>
                {pf ? <td className="r">{pct(books[0].notional[j], 1)}</td> : <><td className="r">{num(books[1].notional[j], 2)}</td>
                  <td className="r"><V x={S.weights[j]} f={(x) => num(x, 2, true)} /></td>
                  <td className="r"><V x={books[0].notional[j]} f={(x) => num(x, 2, true)} /></td><td className="r">{pct(S.go[j], 0)}</td></>}</tr>
            ))}</tbody>
          </table>
        </TableWrap>
        {!pf && <div className="row-gap">
          <span className="label">Риск на актив:</span>
          <Segmented value={risk} onChange={setRisk} label="Риск" options={S.risks.map((x) => ({ value: x, label: pct(x, x < 0.1 ? 1 : 0) }))} />
        </div>}
      </Card>
      <Card title={pf ? "Убыток портфеля в сценариях" : "Убыток счёта в сценариях"} sub={pf
        ? <>Доля капитала. В длинных окнах взяты худшие 5 дней внутри.</>
        : <>Доля суммы для торговли; в скобках — доля денег на брокерском счёте реального счёта (там лежит {pct(ms, 0)} суммы). «Худший знак» — каждая полная позиция на неудачной стороне. В длинных окнах взяты худшие 5 дней внутри.</>}>
        <TableWrap label="Сценарии">
          <table className="compact">
            <thead><tr><th>Сценарий</th>{books.map((b) => <th key={b.name} className="r">{b.name}</th>)}</tr></thead>
            {groups.map((g) => (
              <tbody key={g.title}>
                <tr className="group"><td colSpan={books.length + 1}>{g.title}</td></tr>
                {g.rows.map((row) => <tr key={row.label}><td>{row.label}</td>{books.map((b) => <Fragment key={b.name}>{cell(b, row)}</Fragment>)}</tr>)}
              </tbody>
            ))}
          </table>
        </TableWrap>
      </Card>
      <Card title="Свои сценарии" sub="Движение каждого актива в процентах; таблица выше пересчитывается сразу.">
        <TableWrap label="Редактор сценариев">
          <table className="compact editor">
            <thead><tr><th>Сценарий</th>{r.meta.labels.map((l, j) => <th key={j}><AssetName label={l} slot={slots[j]} /></th>)}<th></th></tr></thead>
            <tbody>
              {hyp.map((h, i) => (
                <tr key={i}>
                  <td><input value={h.label} aria-label="Название сценария" onChange={(e) => setHyp(hyp.map((x, k) => k === i ? { ...x, label: e.target.value } : x))} /></td>
                  {Array.from({ length: n }, (_, j) => (
                    <td key={j}><input type="number" step={1} value={Math.round((h.moves[j] ?? 0) * 100) / 100} aria-label={`${r.meta.labels[j]}, %`}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setHyp(hyp.map((x, k) => k === i ? { ...x, moves: Array.from({ length: n }, (_, q) => q === j ? v : x.moves[q] ?? 0) } : x));
                      }} /></td>
                  ))}
                  <td><button type="button" className="icon" aria-label="Удалить сценарий" onClick={() => setHyp(hyp.filter((_, k) => k !== i))}>×</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <button type="button" className="ghost" onClick={() => setHyp([...hyp, { label: `сценарий ${hyp.length + 1}`, moves: Array(n).fill(-10) }])}>+ сценарий</button>
      </Card>
      <Note>Вероятность чёрного лебедя оценить нельзя, но можно потребовать, чтобы ни один сценарий из списка не убил счёт: ΔV = Σ w<sub>i</sub>N<sub>i</sub>r<sub>i</sub>. Риск — главный рычаг: убыток растёт пропорционально ему, пока не упрётся в предел ГО.</Note>
    </>
  );
}

// ---------------------------------------------------------------------------- tails

function tailTable(title: string, t: TailNumbers) {
  return (
    <TableWrap label={title}>
      <table className="compact">
        <thead><tr><th>{title}</th><th className="r">EVT</th><th className="r">Нормальное</th><th className="r">История</th></tr></thead>
        <tbody>
          {t.levels.map((l) => (
            <tr key={"v" + l.q}><td>VaR {pct(l.q, l.q > 0.99 ? 1 : 0)}</td>{l.var.map((v, k) => <td key={k} className="r">{pct(v, 1)}</td>)}</tr>
          ))}
          {t.levels.map((l) => (
            <tr key={"e" + l.q}><td>ES {pct(l.q, l.q > 0.99 ? 1 : 0)}</td>{l.es.map((v, k) => <td key={k} className="r">{pct(v, 1)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

export function Tails({ r, slots }: P) {
  const t = useTheme();
  const T = r.tails;
  const [asset, setAsset] = useState(0);
  const surv = useMemo((): Option => ({
    ...base(t),
    legend: legend(t),
    grid: { left: 8, right: 16, top: 40, bottom: 28, containLabel: true },
    tooltip: { ...base(t).tooltip, trigger: "item",
      formatter: (p: { seriesName: string; value: number[] }) => `${p.seriesName}<br/>убыток ${pct(p.value[0], 1)}: раз в ${num(1 / p.value[1] / r.meta.ppy, 1)} лет` },
    xAxis: axis(t, { type: "value", name: "дневной убыток счёта", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.ink3 },
      axisLabel: { color: t.ink3, formatter: (v: number) => pct(v, 0) }, splitLine: { show: false } }),
    yAxis: axis(t, { type: "log", axisLabel: { color: t.ink3, formatter: (v: number) => v >= 0.01 ? pct(v, 0) : v.toExponential(0) } }),
    series: [
      { name: "история", type: "scatter", symbolSize: 6, data: T.survival.empirical, itemStyle: { color: t.series[0], borderColor: t.sheet, borderWidth: 1 } },
      { name: "обобщённое Парето (EVT)", type: "line", showSymbol: false, data: T.survival.gpd, lineStyle: { color: t.series[1], width: 2 }, itemStyle: { color: t.series[1] } },
      { name: "нормальное", type: "line", showSymbol: false, data: T.survival.normal, lineStyle: { color: t.gray, width: 2 }, itemStyle: { color: t.gray } },
    ],
  }), [t, T, r.meta.ppy]);
  const hist = useMemo((): Option => {
    const cats = T.histogram.centers.map((c) => pct(c, 1));
    const o = bars(t, cats, [{ name: "дней", values: T.histogram.counts, color: t.series[0] }], { yFmt: (v) => num(v, 0) });
    o.series.push({ name: "нормальное", type: "line", data: T.histogram.normal, showSymbol: false, smooth: true,
      lineStyle: { color: t.series[1], width: 2 }, itemStyle: { color: t.series[1] } });
    o.legend = legend(t);
    o.grid.top = 40;
    o.series[0].barCategoryGap = "8%";
    return o;
  }, [t, T]);
  const A = T.assets[asset];
  const hill = useMemo((): Option => ({
    ...base(t), legend: legend(t),
    grid: { left: 8, right: 16, top: 40, bottom: 28, containLabel: true },
    tooltip: { ...base(t).tooltip },
    xAxis: axis(t, { type: "category", data: A?.hill_k ?? [], name: "k худших дней", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.ink3 }, splitLine: { show: false } }),
    yAxis: axis(t, { type: "value", axisLabel: { color: t.ink3, formatter: (v: number) => num(v, 2) } }),
    series: [
      { name: "падения", type: "line", data: A?.hill_down_curve ?? [], symbolSize: 8, lineStyle: { color: t.series[7], width: 2 }, itemStyle: { color: t.series[7] } },
      { name: "рост", type: "line", data: A?.hill_up_curve ?? [], symbolSize: 8, lineStyle: { color: t.series[0], width: 2 }, itemStyle: { color: t.series[0] } },
    ],
  }), [t, A]);
  return (
    <>
      <Card title="Хвост дневного убытка счёта" sub={<>Превышения над 95-м процентилем убытков подогнаны обобщённым Парето: ξ = {num(T.day.xi, 2)} для дней, {num(T.week.xi, 2)} для недель (0 — хвост как у нормального, больше 0 — толстый). Эксцесс дня {num(T.day.kurt, 1)}.</>}>
        <div className="two">
          <Chart option={surv} height={320} label="Вероятность дневного убытка больше заданного: история, EVT и нормальное" />
          <div>
            <TableWrap label="Убыток раз в N лет">
              <table className="compact">
                <thead><tr><th>Дневной убыток раз в</th><th className="r">EVT</th><th className="r">Нормальное</th></tr></thead>
                <tbody>{T.day.once.map((o) => <tr key={o.years}><td>{o.years} {o.years === 1 ? "год" : o.years < 5 ? "года" : "лет"}</td><td className="r">{pct(o.evt, 1)}</td><td className="r">{pct(o.normal, 1)}</td></tr>)}</tbody>
              </table>
            </TableWrap>
            <p className="foot">Худшие дни: {T.worst.map((w) => `${day(w.date)} ${pct(w.r, 1)}`).join(", ")}.</p>
          </div>
        </div>
        <div className="two">
          {tailTable("День", T.day)}
          {tailTable("Неделя", T.week)}
        </div>
      </Card>
      <Card title="Распределение дневных доходностей счёта">
        <Chart option={hist} height={240} label="Гистограмма дневных доходностей и нормальное распределение" />
      </Card>
      <Card title="Хвосты активов" sub="По всей истории каждого актива. Хилл и GPD — две оценки одного индекса ξ; если они расходятся, хвост оценён плохо.">
        <TableWrap label="Хвосты активов">
          <table className="compact">
            <thead><tr><th>Актив</th><th className="r">ξ падений (GPD)</th><th className="r">ξ роста (GPD)</th><th className="r">Хилл падений</th>
              <th className="r">Хилл роста</th><th className="r">Эксцесс</th><th className="r">Асимметрия</th><th className="r">Дней</th></tr></thead>
            <tbody>{T.assets.map((a, j) => (
              <tr key={j} className={j === asset ? "sel" : ""} onClick={() => setAsset(j)}>
                <td><AssetName label={a.label} slot={slots[j]} /></td><td className="r">{num(a.xi_down, 2)}</td><td className="r">{num(a.xi_up, 2)}</td>
                <td className="r">{num(a.hill_down, 2)}</td><td className="r">{num(a.hill_up, 2)}</td><td className="r">{num(a.kurt, 1)}</td>
                <td className="r">{num(a.skew, 2)}</td><td className="r">{a.n}</td></tr>
            ))}</tbody>
          </table>
        </TableWrap>
        <div className="row-gap">
          <span className="label">График Хилла:</span>
          <select value={asset} onChange={(e) => setAsset(Number(e.target.value))} aria-label="Актив для графика Хилла">
            {T.assets.map((a, j) => <option key={j} value={j}>{a.label}</option>)}
          </select>
          {A && <span className="muted"><span style={{ color: slotColor(t, slots[asset]) }}>●</span> устойчивый участок кривой — оценка ξ</span>}
        </div>
        <Chart option={hill} height={240} label="Оценка Хилла индекса хвоста в зависимости от числа худших дней" />
      </Card>
      <Note>Опасен не обычный плохой день, а гэп без выхода (раздел «Сценарии») и долгая серия убытков (раздел «Просадка»). Если у роста ξ больше, чем у падений (юань, золото в рублях), — шорт опаснее лонга: девальвация приходит гэпом.</Note>
    </>
  );
}
