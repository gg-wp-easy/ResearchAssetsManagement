import { Fragment, useEffect, useState } from "react";
import { api, type FactorRequest, type MLLab, type MLRow } from "./api";
import { FactorDetail, LAB_KEY, savedLabRequest } from "./Factors";
import { day, num, pct } from "./format";
import { Card, Note, TableWrap, V } from "./ui";
import { Guide, Term } from "./help";

export function MLPage() {
  const [req, setReq] = useState<FactorRequest>(savedLabRequest);
  const [res, setRes] = useState<MLLab | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sel, setSel] = useState("ml_price_gbm");

  const run = (r: FactorRequest) => {
    setBusy(true);
    setError("");
    try { localStorage.setItem(LAB_KEY, JSON.stringify(r)); } catch { /* storage blocked */ }
    api.ml(r).then(setRes).catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
  };
  useEffect(() => { run(req); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const years = Array.from({ length: 2025 - 2015 }, (_, i) => 2015 + i);
  const rowKey = (x: MLRow) => x.key.startsWith("ml_") ? x.key : `${x.set}_${x.key}`;
  const chosen = res?.rows.find((x) => rowKey(x) === sel) ?? res?.rows[0];
  return (
    <div className="lab">
      <header className="lab-head">
        <h1>ML-прогноз доходности акций</h1>
        <p>Могут ли модели машинного обучения, сложив факторы и оценку SAS, упорядочить акции по доходности следующего месяца лучше одного простого фактора? Модель учится только на прошлом: прогноз на месяц делают модели, обученные на месяцах до него.</p>
      </header>
      <Guide id="ml" />

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
          {busy && <span className="hint">Первый расчёт: срезы ISS (если их ещё нет — около двух минут), оценка SAS на каждый месяц и обучение моделей.</span>}
        </div>
      </Card>

      {error && <Note kind="warn">Не посчиталось: {error}</Note>}
      {!res && busy && <div className="loading"><div className="spinner" /></div>}
      {res && (
        <div className={busy ? "stale" : ""}>
          <Card title="Модели против простых правил" sub={<>Прогноз оценивается как фактор: верхняя пятая часть бумаг по прогнозу против всех бумаг поровну, после издержек оборота. DSR — дефлированный коэффициент Шарпа: вероятность, что Шарп стратегии выше лучшего из {res.meta.trials} испытанных вариантов без всякого умения (все факторы лаборатории и все модели здесь). Убедительно — от 0,95.</>}>
            <TableWrap label="Модели">
              <table className="compact">
                <thead><tr><th>Модель</th><th className="r">Мес.</th><th className="r">IC</th><th className="r">t(IC)</th>
                  <th className="r" title="верхний квинтиль минус все бумаги поровну, в год">Q5 − все</th>
                  <th className="r"><Term k="net">нетто</Term></th><th className="r">t</th>
                  <th className="r" title="доля бумаг верхнего квинтиля, заменённых за месяц">Оборот</th>
                  <th className="r"><Term k="dsr">DSR</Term></th><th className="pl"><Term k="importance">На что смотрит модель</Term></th></tr></thead>
                {res.sets.map((s) => {
                  const rows = res.rows.filter((x) => x.set === s.key);
                  if (!rows.length) return null;
                  return (
                    <Fragment key={s.key}>
                      <tbody>
                        <tr className="group"><td colSpan={10}>{s.title} · {day(rows[0].from)} – {day(rows[0].to)} · обучение от {s.min_train} мес.</td></tr>
                        {rows.map((x) => {
                          const k = rowKey(x);
                          const imp = Object.entries(x.importance).sort((a, b) => b[1] - a[1]).slice(0, 3);
                          const dsr = "dsr" in x.dsr ? x.dsr.dsr : null;
                          return (
                            <tr key={k} className={"pick" + (k === rowKey(chosen!) ? " sel" : "")} onClick={() => setSel(k)} tabIndex={0}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(k); } }}>
                              <td className="nowrap">{x.model === "factor" ? <span className="muted">{x.title}</span> : x.title}</td>
                              <td className="r">{x.months}</td>
                              <td className="r"><V x={x.ic} f={(v) => num(v, 3, true)} /></td>
                              <td className="r">{num(x.ic_t, 1, true)}</td>
                              <td className="r"><V x={x.ex} f={(v) => pct(v, 1, true)} /></td>
                              <td className="r"><V x={x.net} f={(v) => pct(v, 1, true)} /></td>
                              <td className="r muted">{num(x.net_t, 1, true)}</td>
                              <td className="r">{pct(x.turnover, 0)}</td>
                              <td className={"r" + (dsr !== null && dsr >= 0.95 ? " sig" : "")}>{num(dsr, 2)}{dsr !== null && dsr >= 0.95 && <span className="sig-mark">★</span>}</td>
                              <td className="muted pl">{x.model === "sum" ? "все поровну" : imp.map(([f, v]) => `${res.titles[f] ?? f} ${pct(v, 0)}`).join(", ")}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </Fragment>
                  );
                })}
              </table>
            </TableWrap>
            <p className="foot">«Сумма рангов» — все факторы с заранее заданными знаками без обучения. Строки серым — один фактор на тех же месяцах. «На что смотрит модель» — насколько растёт ошибка последней обученной модели, если перемешать признак (доля от суммы).</p>
          </Card>

          {chosen && <FactorDetail f={chosen} />}

          <Note>
            Как устроено. Признаки — ранги факторов в месяце, цель — ранг доходности следующего месяца: модель учит порядок бумаг, а не уровень рынка. Прогноз на месяц делают модели, обученные на всех месяцах до него (их доходности к этому моменту уже известны), переобучение раз в {res.meta.refit} месяца. Параметры моделей заданы заранее и на проверке не подбирались. Линейная — гребневая регрессия; бустинг — деревья глубины 3, 150 шагов; нейросеть — 16 нейронов tanh с ранней остановкой. Набор «все факторы» начинается в 2022 году вместе с отчётностью, поэтому проверен только на {res.rows.find((x) => x.set === "all")?.months ?? 0} месяцах.
          </Note>
        </div>
      )}
    </div>
  );
}
