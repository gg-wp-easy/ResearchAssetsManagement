import { useMemo, useState } from "react";
import type { StudyResult } from "./api";
import { axis, base, Chart, legend, timeLines, type Option } from "./charts";
import { day, num, pct, years } from "./format";
import { slotColor, useTheme } from "./theme";
import { AssetName, Card, Note, Segmented, TableWrap, Tile, V } from "./ui";

type P = { r: StudyResult; slots: number[] };

// ---------------------------------------------------------------------------- drawdown control

export function Drawdown({ r }: P) {
  const t = useTheme();
  const D = r.drawdown;
  const chosen = D.rows.findIndex((x) => x.chosen);
  const show = useMemo(() => {
    const keys = new Set([0, 1, 7, chosen]);
    return D.rows.map((_, i) => keys.has(i));
  }, [D, chosen]);
  const colors = [t.gray, t.series[7], t.series[3], t.series[1], t.series[2], t.series[4], t.series[5], t.series[0], t.series[6], t.series[0]];
  const eq = useMemo(() => timeLines(t, D.equity.dates, D.rows.map((row, i) => ({ name: row.name, values: D.equity.values[i],
    color: colors[i] ?? t.gray, width: i === chosen ? 2.5 : 1.5 })).filter((_, i) => show[i]),
    { log: true, zoom: true, yFmt: (v) => num(v, v < 10 ? 1 : 0), tipFmt: (v) => num(v, 2) }), [t, D, show, chosen]); // eslint-disable-line react-hooks/exhaustive-deps
  const curves = useMemo((): Option => ({
    ...base(t), legend: legend(t, { type: "scroll" }),
    grid: { left: 8, right: 16, top: 44, bottom: 28, containLabel: true },
    tooltip: { ...base(t).tooltip, valueFormatter: (v: number) => num(v, 2) },
    xAxis: axis(t, { type: "category", data: D.multipliers.dd.map((d) => pct(d, 0)), name: "просадка от пика", nameLocation: "middle",
      nameGap: 26, nameTextStyle: { color: t.ink3 }, splitLine: { show: false }, axisLabel: { color: t.ink3, interval: 9 } }),
    yAxis: axis(t, { type: "value", min: 0, max: 1.05, axisLabel: { color: t.ink3, formatter: (v: number) => num(v, 2) } }),
    series: D.multipliers.curves.map((c) => {
      const i = D.rows.findIndex((x) => x.name === c.name);
      return { name: c.name, type: "line", data: c.values, showSymbol: false, step: c.name.startsWith("ступени") || c.name.startsWith("стоп") ? "end" : undefined,
        lineStyle: { color: colors[i] ?? t.gray, width: i === chosen ? 2.5 : 1.5 }, itemStyle: { color: colors[i] ?? t.gray } };
    }),
  }), [t, D, chosen]); // eslint-disable-line react-hooks/exhaustive-deps
  const horizons = Object.keys(D.odds[0]?.odds ?? {});
  const levels = Object.keys(D.odds[0]?.odds[horizons[0]] ?? {});
  return (
    <>
      <Card title="Контроль просадки" sub="Тот же счёт с разными правилами урезания размера при просадке. Сравнение — с вариантом без контроля, разница по неделям (t ≥ 2 по модулю — уже не случайность).">
        <TableWrap label="Контроль просадки">
          <table className="compact">
            <thead><tr><th>Контроль</th><th className="r">В год</th><th className="r">Шарп</th><th className="r">Просадка</th><th className="r">Calmar</th>
              <th className="r">Худш. месяц</th><th className="r">Худш. год</th><th className="r">Под водой</th><th className="r">Урезано дней</th>
              <th className="r">Против без контроля</th></tr></thead>
            <tbody>{D.rows.map((row, i) => (
              <tr key={i} className={row.chosen ? "sel" : ""}>
                <td>{row.name}{row.chosen && <span className="badge">выбран</span>}</td>
                <td className="r"><V x={row.stats.cagr} f={(x) => pct(x, 1, true)} /></td><td className="r">{num(row.stats.sharpe, 2)}</td>
                <td className="r">{pct(row.stats.dd, 1)}</td><td className="r">{num(row.stats.calmar, 2)}</td>
                <td className="r">{pct(row.stats.worst_month, 1)}</td><td className="r">{pct(row.stats.worst_year, 1)}</td>
                <td className="r">{num(row.stats.underwater, 1)} г</td><td className="r">{pct(row.stats.cut, 0)}</td>
                <td className="r nowrap">{row.stats.vs_base !== undefined ? <><V x={row.stats.vs_base} f={(x) => pct(x, 1, true)} /> в год, t {num(row.stats.t, 1)}</> : "–"}</td>
              </tr>
            ))}</tbody>
          </table>
        </TableWrap>
      </Card>
      <div className="two">
        <Card title="Множитель размера"><Chart option={curves} height={300} label="Множитель размера позиций в зависимости от просадки" /></Card>
        <Card title="Капитал с контролем" sub="Без контроля, стоп бота, «с 10% до 35%» и выбранный.">
          <Chart option={eq} height={300} label="Капитал при разных контролях просадки" />
        </Card>
      </div>
      <Card title="Вероятность просадки: блочный бутстреп" sub="Дневные доходности счёта без контроля, перемешанные блоками по 21 дню; на каждом пути размер умножен на множитель вчерашней просадки. Контроли со скользящим пиком в бутстрепе не считаются.">
        <TableWrap label="Бутстреп просадок">
          <table className="compact">
            <thead>
              <tr><th rowSpan={2}>Контроль</th>{horizons.map((h) => <th key={h} colSpan={levels.length + 1} className="c">за {h} {h === "1" ? "год" : "года"}</th>)}</tr>
              <tr>{horizons.map((h) => [...levels.map((l) => <th key={h + l} className="r">&gt;{pct(Number(l), 0)}</th>), <th key={h + "m"} className="r">медиана</th>])}</tr>
            </thead>
            <tbody>{D.odds.map((o) => (
              <tr key={o.name}><td>{o.name}</td>{horizons.map((h) => [...levels.map((l) => <td key={h + l} className="r">{pct(o.odds[h][l], 0)}</td>),
                <td key={h + "m"} className="r muted">{pct(o.median[h], 0)}</td>])}</tr>
            ))}</tbody>
          </table>
        </TableWrap>
      </Card>
      <Note>Гроссман–Чжоу (1993): если нельзя падать ниже доли α от пика, в риске держат величину, пропорциональную запасу над полом. Стоп фиксирует убыток и пропускает восстановление; сильный контроль почти равен меньшему риску; мёртвая зона до 10% стоит дёшево.</Note>
    </>
  );
}

// ---------------------------------------------------------------------------- regimes

export function Regimes({ r, slots }: P) {
  const t = useTheme();
  const G = r.regimes;
  const [view, setView] = useState<"filter" | "smooth">("filter");
  const smooth = view === "smooth";
  const opt = useMemo(() => G.error ? null : timeLines(t, G.dates, [{ name: smooth ? "вероятность (сглаженная)" : "вероятность (фильтр)",
    values: smooth ? G.p_bad_smooth : G.p_bad, color: t.series[7], area: true, width: 1.5 }], {
    yFmt: (v) => pct(v, 0), min: 0, max: 1, zoom: true, legend: false }), [t, G, smooth]);
  if (G.error) return <Note kind="warn">{G.error}</Note>;
  const [calm, bad] = G.states;
  return (
    <>
      <div className="tiles">
        <Tile label="Сейчас плохой режим" value={pct(G.now, 0)} sub="фильтр Гамильтона, последняя неделя" toneClass={G.now > 0.5 ? "neg" : ""} />
        <Tile label="Доля плохих недель" value={pct(bad.share, 0)} sub={`в среднем ${num(bad.duration_weeks, 0)} нед. подряд`} />
        <Tile label="Волатильность в плохом режиме" value={`×${num(bad.mkt_vol / calm.mkt_vol, 1)}`} sub="к спокойному, корзина равного риска" />
        <Tile label="Средняя корреляция" value={`${num(calm.avg_corr, 2)} → ${num(bad.avg_corr, 2)}`} sub="между активами" />
      </div>
      <Card title="Вероятность плохого режима" sub="Двухрежимная скрытая марковская модель на недельной доходности корзины (каждый актив нормирован на свою волатильность). Фильтр — что было известно в тот день; сглаженная — задним числом.">
        <Segmented value={view} onChange={setView} label="Оценка" options={[{ value: "filter", label: "фильтр" }, { value: "smooth", label: "сглаженная" }]} />
        {opt && <Chart option={opt} height={260} label="Вероятность плохого режима по неделям" />}
      </Card>
      <Card title="Режимы">
        <TableWrap label="Режимы">
          <table className="compact">
            <thead><tr><th></th><th className="r">Спокойный</th><th className="r">Плохой</th></tr></thead>
            <tbody>
              <tr><td>Доля недель</td><td className="r">{pct(calm.share, 0)}</td><td className="r">{pct(bad.share, 0)}</td></tr>
              <tr><td>Средняя длительность</td><td className="r">{num(calm.duration_weeks, 0)} нед.</td><td className="r">{num(bad.duration_weeks, 0)} нед.</td></tr>
              <tr><td>Правило: доход в год</td><td className="r"><V x={calm.book_mean} f={(x) => pct(x, 1, true)} /></td><td className="r"><V x={bad.book_mean} f={(x) => pct(x, 1, true)} /></td></tr>
              <tr><td>Правило: волатильность</td><td className="r">{pct(calm.book_vol, 1)}</td><td className="r">{pct(bad.book_vol, 1)}</td></tr>
              <tr><td>Правило: Шарп</td><td className="r">{num(calm.book_sharpe, 2)}</td><td className="r">{num(bad.book_sharpe, 2)}</td></tr>
              <tr className="group"><td colSpan={3}>активы: доход в год / волатильность</td></tr>
              {r.meta.labels.map((l, j) => (
                <tr key={j}><td><AssetName label={l} slot={slots[j]} /></td>
                  <td className="r"><V x={calm.assets[j].mean} f={(x) => pct(x, 0, true)} /> / {pct(calm.assets[j].vol, 0)}</td>
                  <td className="r"><V x={bad.assets[j].mean} f={(x) => pct(x, 0, true)} /> / {pct(bad.assets[j].vol, 0)}</td></tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <p className="foot">Матрица переходов: остаться в спокойном {pct(G.transition[0][0], 1)}, в плохом {pct(G.transition[1][1], 1)} за неделю.</p>
      </Card>
      <Note>Кризисных эпизодов в данных — горстка, параметры плохого режима оцениваются по нескольким точкам. Режим разумно использовать как множитель риска (волатильность и корреляции), а не как сигнал направления.</Note>
    </>
  );
}

// ---------------------------------------------------------------------------- allocation

export function Allocation({ r, slots }: P) {
  const t = useTheme();
  const A = r.allocation;
  const [method, setMethod] = useState("erc");
  const colors = [t.series[0], t.series[1], t.series[2], t.series[3], t.series[4], t.series[6], t.series[7], t.gray];
  const eq = useMemo(() => A.error ? null : timeLines(t, A.equity.dates, A.rows.map((row, i) => ({ name: row.title, values: A.equity.values[i],
    color: colors[i], width: row.key === "book" ? 2.5 : 1.5 })), { log: true, zoom: true, yFmt: (v) => num(v, v < 10 ? 1 : 0), tipFmt: (v) => num(v, 2) }),
  [t, A]); // eslint-disable-line react-hooks/exhaustive-deps
  const hist = A.history?.[method] ?? [];
  const wopt = useMemo((): Option | null => {
    if (A.error || !hist.length) return null;
    return {
      ...base(t), legend: legend(t, { type: "scroll" }),
      grid: { left: 8, right: 16, top: 44, bottom: 8, containLabel: true },
      tooltip: { ...base(t).tooltip, valueFormatter: (v: number) => pct(v, 0) },
      xAxis: axis(t, { type: "category", data: hist.map((h) => h.date), splitLine: { show: false }, axisLabel: { color: t.ink3, formatter: (d: string) => d.slice(0, 4) } }),
      yAxis: axis(t, { type: "value", min: 0, max: 1, axisLabel: { color: t.ink3, formatter: (v: number) => pct(v, 0) } }),
      series: A.labels.map((l, j) => ({ name: l, type: "bar", stack: "w", barCategoryGap: "10%", data: hist.map((h) => h.w[j]),
        itemStyle: { color: slotColor(t, slots[j]), borderColor: t.sheet, borderWidth: 1 } })),
    };
  }, [t, A, hist, slots]);
  if (A.error) return <Note kind="warn">{A.error}</Note>;
  return (
    <>
      <Card title="Распределение капитала" sub={<>Только лонг, весь капитал в активах, оценка на последних {A.window_weeks} неделях, держим {A.hold_weeks} недель и пересчитываем: каждая доходность — вне выборки. {day(A.from)} – {day(A.to)}. Для сравнения — правило тренда и «держать».</>}>
        <TableWrap label="Методы распределения">
          <table className="compact">
            <thead><tr><th>Метод</th><th className="r">В год</th><th className="r">Вол.</th><th className="r">Шарп</th><th className="r">Просадка</th>
              <th className="r">Худшая неделя</th><th className="r">CVaR 95% нед.</th><th className="r">Оборот</th><th className="pl">Веса сейчас</th></tr></thead>
            <tbody>{A.rows.map((row) => (
              <tr key={row.key} className={row.key === "book" ? "sel" : ""}>
                <td>{row.title}</td><td className="r"><V x={row.cagr} f={(x) => pct(x, 1, true)} /></td><td className="r">{pct(row.vol, 1)}</td>
                <td className="r">{num(row.sharpe, 2)}</td><td className="r">{pct(row.dd, 1)}</td><td className="r">{pct(row.worst_week, 1)}</td>
                <td className="r">{pct(row.cvar95, 1)}</td><td className="r">{row.turnover === null ? "–" : pct(row.turnover, 0)}</td>
                <td className="pl">{row.now ? <WeightBar w={row.now} slots={slots} labels={A.labels} /> : <span className="muted">–</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        </TableWrap>
        <p className="foot">Доходности — сверх стоимости удержания. Оборот — средняя сумма |Δw| за пересчёт. «Максимум Шарпа» по оценённым средним обычно хуже простых методов: средние доходности оцениваются с огромной ошибкой.</p>
      </Card>
      {eq && <Card title="Капитал"><Chart option={eq} height={320} label="Капитал методов распределения" /></Card>}
      <Card title="Веса во времени">
        <Segmented value={method} onChange={setMethod} label="Метод" options={[{ value: "erc", label: "паритет риска" }, { value: "min_cvar", label: "минимум CVaR" }, { value: "max_sharpe", label: "максимум Шарпа" }]} />
        {wopt && <Chart option={wopt} height={260} label="Веса активов при каждом пересчёте" />}
      </Card>
      <Note>Минимум CVaR — линейная программа Рокафеллара–Урясева по неделям окна: min ζ + Σu<sub>s</sub>/((1−α)S) при u<sub>s</sub> ≥ −wᵀr<sub>s</sub> − ζ, u<sub>s</sub> ≥ 0. Паритет риска — равные вклады w<sub>i</sub>(Σw)<sub>i</sub>.</Note>
    </>
  );
}

function WeightBar({ w, slots, labels }: { w: number[]; slots: number[]; labels: string[] }) {
  const t = useTheme();
  return (
    <div className="wbar" role="img" aria-label={labels.map((l, j) => `${l} ${pct(w[j], 0)}`).join(", ")}
      title={labels.map((l, j) => `${l}: ${pct(w[j], 0)}`).join("\n")}>
      {w.map((v, j) => v > 0.004 ? <i key={j} style={{ width: `${v * 100}%`, background: slotColor(t, slots[j]) }} /> : null)}
    </div>
  );
}

// ---------------------------------------------------------------------------- Kelly and Sharpe

export function Sizing({ r }: P) {
  const t = useTheme();
  const K = r.sizing.kelly, S = r.sizing.significance, H = r.sizing.vs_hold, B = r.sizing.vs_base;
  const opt = useMemo((): Option => {
    const marks: [number, string][] = [[K.c_now, "счёт"], [0.5, "половина Келли"], [1, "Келли"], [2, "2 × Келли"]];
    return {
      ...base(t),
      grid: { left: 8, right: 24, top: 24, bottom: 30, containLabel: true },
      tooltip: { ...base(t).tooltip, formatter: (ps: { value: number[] }[]) => {
        const c = ps[0].value[0];
        return `доля Келли <b>${num(c, 2)}</b><br/>рост ${pct(2 * c - c * c, 0)} максимума<br/>волатильность ${pct(c * K.kelly_vol, 0)}`;
      } },
      xAxis: axis(t, { type: "value", min: 0, max: 2.2, name: "доля Келли c", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.ink3 },
        axisLabel: { color: t.ink3, formatter: (v: number) => num(v, 1) }, splitLine: { show: false } }),
      yAxis: axis(t, { type: "value", min: -0.5, max: 1.1, axisLabel: { color: t.ink3, formatter: (v: number) => pct(v, 0) } }),
      series: [
        { type: "line", data: K.curve, showSymbol: false, lineStyle: { color: t.series[0], width: 2 }, itemStyle: { color: t.series[0] } },
        { type: "scatter", symbolSize: 10, data: marks.filter(([c]) => c <= 2.2).map(([c, name]) => ({ value: [c, 2 * c - c * c], name })),
          itemStyle: { color: t.series[0], borderColor: t.sheet, borderWidth: 2 },
          label: { show: true, formatter: (p: { name: string }) => p.name, position: "top", color: t.ink2, fontSize: 11 } },
      ],
    };
  }, [t, K]);
  return (
    <>
      <div className="tiles">
        <Tile label="Шарп" value={`${num(S.sharpe, 2)} ± ${num(2 * S.se, 2)}`} sub={`два стандартных отклонения, ${years(S.years)}`} />
        <Tile label="Келли: плечо к счёту" value={num(K.f_star, 1) + "×"} sub={`волатильность Келли ${pct(K.kelly_vol, 0)}`} />
        <Tile label="Счёт держит" value={num(K.c_now, 2) + " Келли"} sub={K.growth_now !== null ? `${pct(K.growth_now, 0)} максимального роста` : ""} />
        <Tile label="c* с ошибкой оценки" value={num(K.c_star, 2)} sub="T·SR² / (T·SR² + 1)" />
      </div>
      <Card title="Критерий Келли" sub={<>g(c f*) / g* = 2c − c²: при вдвое большей доле, чем у Келли, рост падает до нуля. μ = {pct(K.mu, 1)}, σ = {pct(K.vol, 1)} в год.</>}>
        <Chart option={opt} height={280} label="Рост капитала в зависимости от доли Келли" />
        <p className="foot">Против полного Келли — гэпы без выхода (раздел «Сценарии») и то, что правило выбрано из многих проверенных (ниже): истинный Шарп, скорее всего, ниже оценки.</p>
      </Card>
      <Card title="Сколько стоит оценка Шарпа">
        <div className="two">
          <div>
            <h4>Лучший из K вариантов без всякого преимущества</h4>
            <TableWrap label="Ожидаемый максимум Шарпа">
              <table className="compact">
                <thead><tr><th>История</th>{S.luck[0].values.map((v) => <th key={v.k} className="r">K = {v.k}</th>)}</tr></thead>
                <tbody>{S.luck.map((l) => (
                  <tr key={l.years}><td>{years(l.years)}</td>{l.values.map((v) => <td key={v.k} className="r">{num(v.sr, 2)}</td>)}</tr>
                ))}</tbody>
              </table>
            </TableWrap>
          </div>
          <div>
            <h4>Лет до вывода (t = 2) о разнице Шарпов</h4>
            <TableWrap label="Срок проверки">
              <table className="compact">
                <thead><tr><th>ΔSR</th><th className="r">ρ = 0</th><th className="r">ρ = 0,5</th><th className="r">ρ = 0,9</th></tr></thead>
                <tbody>{[0.2, 0.5].map((d) => (
                  <tr key={d}><td>{num(d, 1)}</td>{S.need.filter((x) => x.dsr === d).map((x) => <td key={x.rho} className="r">{num(x.years, 0)}</td>)}</tr>
                ))}</tbody>
              </table>
            </TableWrap>
          </div>
        </div>
        <TableWrap label="Сравнения">
          <table className="compact">
            <thead><tr><th>Сравнение</th><th className="r">Корреляция</th><th className="r">Шарп</th><th className="r">Разница</th><th className="r">t</th><th className="r">Лет до t = 2</th></tr></thead>
            <tbody>
              {H && <tr><td>правило против «держать»</td><td className="r">{num(H.rho, 2)}</td><td className="r">{num(H.sr_a, 2)} / {num(H.sr_b, 2)}</td>
                <td className="r"><V x={H.diff} f={(x) => num(x, 2, true)} /></td><td className="r">{num(H.t, 1)}</td><td className="r">{num(H.years_needed, 0)}</td></tr>}
              {B && <tr><td>выбранный контроль против без контроля</td><td className="r">{num(B.rho, 2)}</td><td className="r">{num(B.sr_a, 2)} / {num(B.sr_b, 2)}</td>
                <td className="r"><V x={B.diff} f={(x) => num(x, 2, true)} /></td><td className="r">{num(B.t, 1)}</td><td className="r">{num(B.years_needed, 0)}</td></tr>}
            </tbody>
          </table>
        </TableWrap>
        <p className="foot">SE(SR) ≈ √((1 + SR²/2)/T); SE(SR₁ − SR₂) ≈ √(2(1 − ρ)/T) (Lo 2002; Memmel 2003; Bailey, López de Prado 2014). Бумажный счёт, сильно похожий на основной, не докажет разницу Шарпа за разумный срок — он проверяет механику.</p>
      </Card>
    </>
  );
}
