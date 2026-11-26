import { useEffect, useMemo, useState } from "react";
import { api, type FactorLab, type FactorRequest, type FactorRow, type ValuationSummary } from "./api";
import { axis, base, Chart, heat, legend, timeLines, type Option } from "./charts";
import { day, num, pct } from "./format";
import { useTheme } from "./theme";
import { Card, Note, TableWrap, V } from "./ui";
import { Guide, Term } from "./help";

export const LAB_KEY = "ram.factors.v1";
const KEY = LAB_KEY;
const DEFAULT: FactorRequest = { start: "2015-01-01", top: 100, cost: 0.002 };
export const DATA_LABEL: Record<FactorRow["data"], string> = { price: "цены", dividends: "дивиденды", reports: "отчёты",
  valuation: "оценка SAS" };
export const FEATURE_LABEL: Record<string, string> = {
  roe: "ROE", roa: "ROA", npm: "чистая маржа", ebitda_margin: "маржа EBITDA", operating_margin: "операционная маржа",
  fcf_margin: "маржа FCF", cash_conversion: "ОДП / прибыль", cash_assets: "деньги / активы", equity_assets: "капитал / активы",
  asset_turnover: "оборачиваемость активов", roce: "ROCE", capex_revenue: "CAPEX / выручка", capex_amortization: "CAPEX / амортизация",
  payout_ratio: "доля выплат", g: "устойчивый рост g", revenue_growth_1y: "рост выручки за год", revenue_cagr_3y: "рост выручки за 3 года",
  profit_growth_1y: "рост прибыли за год", margin_volatility: "изменчивость маржи", profit_years_share: "доля прибыльных лет",
  log_debt_to_equity: "ln(1 + долг / капитал)", net_debt_ebitda: "чистый долг / EBITDA", interest_coverage: "EBITDA / проценты",
  log_revenue: "размер (ln выручки)", beta: "бета", dividend_consistency: "регулярность дивидендов",
};

export function savedLabRequest(): FactorRequest {
  return saved();
}

function saved(): FactorRequest {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (v && typeof v.start === "string" && typeof v.top === "number" && typeof v.cost === "number") return v;
  } catch { /* storage blocked */ }
  return DEFAULT;
}

export function Factors() {
  const [req, setReq] = useState<FactorRequest>(saved);
  const [res, setRes] = useState<FactorLab | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sel, setSel] = useState("mom");

  const run = (r: FactorRequest) => {
    setBusy(true);
    setError("");
    try { localStorage.setItem(KEY, JSON.stringify(r)); } catch { /* storage blocked */ }
    api.factors(r).then((x) => {
      setRes(x);
      if (!x.factors.some((f) => f.key === sel) && x.factors.length) setSel(x.factors[0].key);
    }).catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
  };
  useEffect(() => { run(req); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const years = Array.from({ length: 2025 - 2015 }, (_, i) => 2015 + i);
  return (
    <div className="lab">
      <header className="lab-head">
        <h1>Факторы акций Мосбиржи</h1>
        <p>Говорит ли признак акции, известный в конце месяца, какие бумаги обгонят остальные в следующем месяце? Каждый месяц — самые ликвидные акции основного режима на ту дату (вместе с теми, что позже ушли с биржи), доходность с дивидендами, отчётность — только опубликованная до даты.</p>
      </header>
      <Guide id="factors" />

      <Card>
        <div className="lab-controls">
          <label className="field">
            <span>Начало</span>
            <select value={req.start} onChange={(e) => setReq({ ...req, start: e.target.value })}>
              {years.map((y) => <option key={y} value={`${y}-01-01`}>{y}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Вселенная</span>
            <select value={req.top} onChange={(e) => setReq({ ...req, top: Number(e.target.value) })}>
              {[50, 100, 150, 250].map((n) => <option key={n} value={n}>{n} самых ликвидных</option>)}
            </select>
          </label>
          <label className="field">
            <span>Издержки за сторону</span>
            <select value={req.cost} onChange={(e) => setReq({ ...req, cost: Number(e.target.value) })}>
              {[0, 0.001, 0.002, 0.005, 0.01].map((c) => <option key={c} value={c}>{pct(c, c && c < 0.01 ? 1 : 0)}</option>)}
            </select>
          </label>
          <button type="button" className="primary" disabled={busy} onClick={() => run(req)}>{busy ? "Считаю…" : "Посчитать"}</button>
          {busy && <span className="hint">Первый расчёт скачивает недельные срезы ISS с 2013 года — около двух минут, дальше — секунды.</span>}
        </div>
      </Card>

      {error && <Note kind="warn">Не посчиталось: {error}</Note>}
      {!res && busy && <div className="loading"><div className="spinner" /></div>}
      {res && <LabResult r={res} sel={sel} onSel={setSel} stale={busy} />}
    </div>
  );
}

function LabResult({ r, sel, onSel, stale }: { r: FactorLab; sel: string; onSel: (k: string) => void; stale: boolean }) {
  const t = useTheme();
  const rows = useMemo(() => [...r.factors].sort((a, b) => Math.abs(b.ic_t ?? 0) - Math.abs(a.ic_t ?? 0)), [r]);
  const f = r.factors.find((x) => x.key === sel) ?? rows[0];
  const T = r.testing;
  const corr = useMemo(() => heat(t, r.corr.titles, r.corr.titles, r.corr.values, { range: 1 }), [t, r]);
  const uni = useMemo(() => timeLines(t, [r.universe.dates[0], ...r.universe.ends], [
    { name: `${r.meta.top} бумаг поровну`, values: [1, ...r.universe.ew], color: t.series[0] },
    { name: "MCFTR (по капитализации)", values: [1, ...r.universe.mcftr], color: t.gray, dashed: true },
  ], { log: true, yFmt: (v) => num(v, 1), tipFmt: (v) => num(v, 2) }), [t, r]);
  return (
    <div className={stale ? "stale" : ""}>
      <p className="period">
        {day(r.meta.from)} – {day(r.meta.to)} · {r.meta.months} мес. · {r.meta.top} самых ликвидных бумаг из {r.meta.tickers} побывавших на TQBR ·
        издержки {pct(r.meta.cost, 1)} за сторону · бумаг вселенной поровну {pct(r.universe.ew_year, 1, true)} в год, MCFTR {pct(r.universe.mcftr_year, 1, true)}
      </p>
      {r.meta.warnings.length > 0 && (
        <details className="warnings">
          <summary>Замечания к данным: {r.meta.warnings.length}</summary>
          <ul>{r.meta.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </details>
      )}

      <Card title="Факторы" sub={<>Строки по убыванию |t(IC)|. Отмечены ★ факторы с |t| выше {num(T.bonferroni, 2)} — порога Бонферрони на {T.k} проверенных факторов; лучший |t| из {T.k} чистых шумов в среднем около {num(T.noise_max, 1)}. Нажмите строку — ниже её квинтили.</>}>
        <TableWrap label="Факторы">
          <table className="compact">
            <thead><tr>
              <th>Фактор</th><th className="r" title="месяцев с данными">Мес.</th><th className="r" title="бумаг в среднем за месяц">Бумаг</th>
              <th className="r"><Term k="ic">IC</Term></th><th className="r"><Term k="t">t(IC)</Term></th>
              <th className="r" title="доля месяцев с IC > 0">IC &gt; 0</th><th className="pl"><Term k="quintile">Квинтили</Term></th>
              <th className="r" title="верхний квинтиль минус нижний, в год">Q5 − Q1</th><th className="r">t</th>
              <th className="r" title="верхний квинтиль минус все бумаги поровну, в год">Q5 − все</th>
              <th className="r"><Term k="net">нетто</Term></th>
              <th className="r"><Term k="turnover">Оборот</Term></th>
            </tr></thead>
            <tbody>{rows.map((x) => (
              <tr key={x.key} className={"pick" + (x.key === f?.key ? " sel" : "")} onClick={() => onSel(x.key)} tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSel(x.key); } }}
                aria-selected={x.key === f?.key}>
                <td className="nowrap" title={x.desc}>{x.title}<span className="data-tag">{DATA_LABEL[x.data]}</span></td>
                <td className="r" title={`${day(x.from)} – ${day(x.to)}`}>{x.months}</td>
                <td className="r">{num(x.names, 0)}</td>
                <td className="r"><V x={x.ic} f={(v) => num(v, 3, true)} /></td>
                <td className={"r" + (x.sig ? " sig" : "")}>{num(x.ic_t, 1, true)}{x.sig && <span className="sig-mark" aria-label="значимо">★</span>}</td>
                <td className="r">{pct(x.ic_hit, 0)}</td>
                <td className="pl"><QBars q={x.q} /></td>
                <td className="r"><V x={x.ls} f={(v) => pct(v, 1, true)} /></td>
                <td className="r muted">{num(x.ls_t, 1, true)}</td>
                <td className="r"><V x={x.ex} f={(v) => pct(v, 1, true)} /></td>
                <td className="r"><V x={x.net} f={(v) => pct(v, 1, true)} /></td>
                <td className="r">{pct(x.turnover, 0)}</td>
              </tr>
            ))}</tbody>
          </table>
        </TableWrap>
        <p className="foot">Знак фактора задан заранее (например, «низкая волатильность» — минус σ): отрицательный t значит, что работает обратное. Квинтили — средняя доходность пятых частей вселенной в год, от низкого значения фактора (Q1) к высокому (Q5). Доходности полные (с дивидендами там, где они известны), не сверх ставки.</p>
      </Card>

      {f && <FactorDetail f={f} />}

      {r.valuation && <ValuationCard v={r.valuation} />}

      {r.fm.length > 0 && (
        <Card title="Фама–Макбет: факторы вместе" sub="Каждый месяц — регрессия доходностей на ранги факторов (стандартизованные), коэффициенты усреднены по месяцам: премия за одно стандартное отклонение фактора при прочих равных, в год.">
          <div className="two">
            {r.fm.map((m) => (
              <TableWrap key={m.key} label={m.title}>
                <table className="compact">
                  <thead><tr><th>{m.title}</th><th className="r">Премия в год</th><th className="r">t</th></tr></thead>
                  <tbody>
                    {m.rows.map((x) => (
                      <tr key={x.key}><td>{x.title}</td><td className="r"><V x={x.coef} f={(v) => pct(v, 1, true)} /></td>
                        <td className={"r" + (Math.abs(x.t ?? 0) > T.bonferroni ? " sig" : "")}>{num(x.t, 1, true)}</td></tr>
                    ))}
                    <tr className="total"><td colSpan={3}>{day(m.from)} – {day(m.to)}, {m.months} мес., R² {num(m.r2, 2)}</td></tr>
                  </tbody>
                </table>
              </TableWrap>
            ))}
          </div>
        </Card>
      )}

      <Card title="Корреляции факторов" sub="Средняя по месяцам ранговая корреляция значений факторов между бумагами: близкие факторы — почти одна ставка.">
        <Chart option={corr} height={Math.max(260, 34 * r.corr.keys.length + 70)} label="Матрица корреляций факторов" />
      </Card>

      <Card title="Вселенная против индекса" sub="Проверка данных: те же бумаги поровну и индекс полной доходности MCFTR. До 2019 года дивидендов в данных нет, поэтому вселенная там отстаёт.">
        <Chart option={uni} height={260} label="Капитал вселенной поровну и MCFTR" />
      </Card>

      <Note>
        Что здесь честно и что нет. Срезы ISS по датам включают бумаги, которые потом ушли с биржи, — у ценовых факторов ошибки выжившего нет. Дивиденды и отчётность — из данных server-analytic-system по сегодняшнему списку T-Invest: у ушедших бумаг их нет (их дивидендная доходность не считается, а факторы по отчётам — только у выживших), отчёты smart-lab — с 2021 года, так что эти факторы проверены на 4–5 годах. Перебрав {T.k} факторов, хоть один «значимый» найдётся случайно — порог |t| &gt; 3 (Харви, Лю, Чжу) строже Бонферрони.
      </Note>
    </div>
  );
}

function QBars({ q }: { q: (number | null)[] }) {
  const vals = q.map((v) => v ?? 0);
  const max = Math.max(0.05, ...vals.map(Math.abs));
  return (
    <span className="qbars-wrap" role="img" aria-label={"квинтили: " + vals.map((v) => pct(v, 0)).join(", ")}
      title={vals.map((v, i) => `Q${i + 1}: ${pct(v, 1, true)}`).join("\n")}>
      <span className="qbars">
        {vals.map((v, i) => <i key={i} className={v < 0 ? "neg" : ""} style={{ height: `${Math.max(2, (Math.abs(v) / max) * 22)}px` }} />)}
      </span>
    </span>
  );
}

function ValuationCard({ v }: { v: ValuationSummary }) {
  const t = useTheme();
  const pe = v.multiples.pe;
  const r2 = useMemo(() => pe ? timeLines(t, v.dates, [
    { name: "регрессия", values: pe.r2.reg, color: t.series[0] },
    { name: "дерево", values: pe.r2.tree, color: t.series[1] },
    { name: "нейросеть", values: pe.r2.nn, color: t.series[2] },
    { name: "только база отрасли", values: pe.r2.base, color: t.gray, dashed: true },
  ], { yFmt: (x) => num(x, 1), tipFmt: (x) => num(x, 2) }) : null, [t, v, pe]);
  const median = (xs: (number | null)[]) => {
    const a = xs.filter((x): x is number => x !== null).sort((x, y) => x - y);
    return a.length ? a[Math.floor(a.length / 2)] : null;
  };
  const ANALYSIS: Record<string, string> = { hybrid: "гибрид", regression: "регрессия", cluster: "кластеры", tree: "дерево", neural: "нейросеть" };
  return (
    <Card title="Оценка SAS на месячных срезах" sub={<>Конвейер server-analytic-system — справедливый мультипликатор = база отрасли с поправкой по показателям отчётности (регрессия, кластеры, дерево, нейросеть и их гибрид) — пересчитан на каждый конец месяца {day(v.dates[0])} – {day(v.dates[v.dates.length - 1])} по отчётам, опубликованным до даты. Каждую компанию оценивают модели, обученные без неё. Строки «SAS …» в таблице факторов — его отклонение ln(справедливый / фактический мультипликатор).</>}>
      {v.parity.map((p) => (
        <p key={p.day} className="foot">
          Сверка с собственным срезом SAS на {day(p.day)}: {p.common} общих компаний из {p.theirs}; P/E совпадает (ранговая корреляция {num(p.multiple_rho, 4)}, медиана отношения {num(p.multiple_median_ratio, 2)}); отклонения — {Object.entries(p.analyses).map(([k, a]) => `${ANALYSIS[k] ?? k} ${num(a.rho, 2)}`).join(", ")}. Расхождение моделей — от трёх повторов кросс-валидации у SAS против одного здесь и другого списка акций.
        </p>
      ))}
      <TableWrap label="Качество оценки">
        <table className="compact">
          <thead><tr><th>Мультипликатор</th><th className="r">Компаний</th>
            <th className="r"><Term k="r2oos">R² регрессии</Term></th><th className="r">R² дерева</th>
            <th className="r">R² нейросети</th><th className="r">R² базы отрасли</th><th className="pl">Чаще всего отобраны</th></tr></thead>
          <tbody>{Object.entries(v.multiples).map(([k, m]) => (
            <tr key={k}><td>{m.label}</td><td className="r">{num(median(m.n), 0)}</td>
              <td className="r">{num(m.r2_mean.reg, 2)}</td><td className="r">{num(m.r2_mean.tree, 2)}</td>
              <td className="r">{num(m.r2_mean.nn, 2)}</td><td className="r muted">{num(m.r2_mean.base, 2)}</td>
              <td className="muted pl">{Object.entries(m.features).slice(0, 4).map(([f, x]) => `${FEATURE_LABEL[f] ?? f} ${pct(x, 0)}`).join(", ")}</td></tr>
          ))}</tbody>
        </table>
      </TableWrap>
      {r2 && <>
        <h4 className="mini-title">P/E: R² вне выборки по месяцам</h4>
        <Chart option={r2} height={220} label="Доля разброса P/E, объяснённая моделями вне выборки, по месяцам" />
      </>}
      <p className="foot">R² — средний по месяцам: доля разброса ln мультипликатора между компаниями, которую модель объясняет у компаний, не участвовавших в обучении. Если R² мал, «справедливый» мультипликатор почти равен отраслевому, и отклонение — это просто дешевизна относительно отрасли. В скобках у показателей — доля блоков кросс-валидации, где отбор его взял.</p>
    </Card>
  );
}

export function FactorDetail({ f }: { f: FactorRow }) {
  const t = useTheme();
  const S = f.series;
  const cum = useMemo(() => timeLines(t, [S.dates[0], ...S.ends], [
    { name: "Q5 — высокий фактор", values: [1, ...S.cum[4]], color: t.series[0] },
    { name: "Q1 — низкий фактор", values: [1, ...S.cum[0]], color: t.series[1] },
    { name: "все бумаги поровну", values: [1, ...S.cum[5]], color: t.gray, dashed: true },
  ], { log: true, zoom: true, yFmt: (v) => num(v, v < 10 ? 1 : 0), tipFmt: (v) => num(v, 2) }), [t, S]);
  const quint = useMemo((): Option => {
    const cats = ["Q1", "Q2", "Q3", "Q4", "Q5", "все"];
    const vals = [...f.q, f.ew];
    return {
      ...base(t),
      grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
      tooltip: { ...base(t).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,0.08)" } },
        valueFormatter: (v: number) => pct(v, 1, true) },
      xAxis: axis(t, { type: "category", data: cats, splitLine: { show: false } }),
      yAxis: axis(t, { type: "value", axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => pct(v, 0) } }),
      series: [{ name: "в год", type: "bar", barMaxWidth: 34,
        data: vals.map((v, i) => ({ value: v, itemStyle: { color: i === 5 ? t.gray : t.series[0], borderRadius: (v ?? 0) >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3] } })),
        label: { show: true, position: "top", color: t.ink2, fontSize: 11, formatter: (p: { value: number }) => pct(p.value, 1) } }],
    };
  }, [t, f]);
  const ic = useMemo((): Option => {
    const roll = S.ic.map((_, i) => {
      if (i < 11) return null;
      const w = S.ic.slice(i - 11, i + 1).filter((v): v is number => v !== null);
      return w.length ? w.reduce((a, b) => a + b, 0) / w.length : null;
    });
    return {
      ...base(t),
      legend: legend(t),
      grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
      tooltip: { ...base(t).tooltip, valueFormatter: (v: number | null) => v === null ? "–" : num(v, 2, true) },
      xAxis: axis(t, { type: "category", data: S.dates, splitLine: { show: false },
        axisLabel: { color: t.ink3, fontSize: 11, formatter: (d: string) => d.slice(0, 4), interval: (i: number) => S.dates[i]?.slice(5, 7) === "01" } }),
      yAxis: axis(t, { type: "value", axisLabel: { color: t.ink3, fontSize: 11, formatter: (v: number) => num(v, 1) } }),
      series: [
        { name: "IC месяца", type: "bar", barCategoryGap: "20%", itemStyle: { color: t.divPos },
          data: S.ic.map((v) => ({ value: v, itemStyle: { color: (v ?? 0) >= 0 ? t.divPos : t.divNeg } })) },
        { name: "среднее за 12 месяцев", type: "line", data: roll, showSymbol: false, lineStyle: { color: t.ink, width: 2 }, itemStyle: { color: t.ink } },
      ],
    };
  }, [t, S]);
  return (
    <Card title={`${f.title}: квинтили`} sub={<>{f.desc}. {day(f.from)} – {day(f.to)}, {f.months} мес., в среднем {num(f.names, 0)} бумаг. IC {num(f.ic, 3, true)} (t {num(f.ic_t, 1, true)}), Q5 − Q1 {pct(f.ls, 1, true)} в год (t {num(f.ls_t, 1, true)}), Q5 против всех после издержек {pct(f.net, 1, true)} в год.</>}>
      <Chart option={cum} height={300} label={`Капитал верхнего и нижнего квинтиля по фактору ${f.title}`} />
      <div className="two">
        <div>
          <h4 className="mini-title">Доходность квинтилей в год</h4>
          <Chart option={quint} height={220} label={`Средняя доходность квинтилей по фактору ${f.title}`} />
        </div>
        <div>
          <h4 className="mini-title">IC по месяцам</h4>
          <Chart option={ic} height={220} label={`Ранговая корреляция фактора ${f.title} с доходностью следующего месяца`} />
        </div>
      </div>
    </Card>
  );
}
