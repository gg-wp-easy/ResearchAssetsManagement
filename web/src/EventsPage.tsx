import { useEffect, useMemo, useState } from "react";
import { api, type CodeCheck, type EventCoverage, type ExchangeEvent, type PortfolioCheck, type StopItem } from "./api";
import { addToStoplist, EventLine, StatusTag } from "./eventsUi";
import { day, pct } from "./format";
import { Guide, Term } from "./help";
import { Card, Note, TableWrap } from "./ui";

export function EventsPage() {
  const [pfs, setPfs] = useState<PortfolioCheck[] | null>(null);
  const [cov, setCov] = useState<EventCoverage | null>(null);
  const [feed, setFeed] = useState<ExchangeEvent[] | null>(null);
  const [days, setDays] = useState(90);
  const [stop, setStop] = useState<StopItem[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const loadPortfolios = () => {
    setBusy("portfolios");
    api.eventsPortfolios().then((r) => { setPfs(r.portfolios); setCov(r.coverage); })
      .catch((e) => setError((e as Error).message)).finally(() => setBusy(""));
  };
  useEffect(() => {
    loadPortfolios();
    api.stoplist().then((r) => setStop(r.items)).catch(() => { /* shown empty */ });
  }, []);
  useEffect(() => {
    api.eventsFeed(days).then((r) => { setFeed(r.events); setCov(r.coverage); }).catch((e) => setError((e as Error).message));
  }, [days]);

  const refresh = () => {
    setBusy("update");
    setError("");
    api.eventsUpdate().then((c) => { setCov(c); loadPortfolios(); return api.eventsFeed(days); })
      .then((r) => setFeed(r.events)).catch((e) => setError((e as Error).message)).finally(() => setBusy(""));
  };
  const toStop = async (code: string, reason: string) => {
    setBusy(code);
    try { setStop(await addToStoplist(code, reason)); loadPortfolios(); } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  };
  const saveStop = async (items: StopItem[]) => {
    try { setStop((await api.saveStoplist(items)).items); loadPortfolios(); } catch (e) { setError((e as Error).message); }
  };

  return (
    <div className="lab">
      <header className="lab-head">
        <h1>События Мосбиржи</h1>
        <p>Дефолты, банкротства, делистинг, приостановка торгов, включение в сектор повышенного риска — из решений самой биржи, разобранных по бумагам и эмитентам. Бумага с таким событием продаётся на следующий торговый день после новости, её вес делится между остальными; дефолт по облигациям выводит и акции того же эмитента.</p>
      </header>
      <Guide id="events" />
      <Card>
        <div className="lab-controls">
          <p className="period" style={{ margin: 0 }}>
            {cov ? <>Лента: {day(cov.from)} – {day(cov.to)} · {cov.news.toLocaleString("ru-RU")} новостей, прочитано решений {cov.read.toLocaleString("ru-RU")}
              {cov.checked ? <> · проверено {new Date(cov.checked * 1000).toLocaleString("ru-RU")}</> : null}</> : "Загружаю ленту…"}
          </p>
          <button type="button" className="ghost small" disabled={busy === "update"} onClick={refresh}>
            {busy === "update" ? "Читаю ленту…" : "Обновить ленту сейчас"}</button>
        </div>
        <p className="hint">Сайт сам перечитывает ленту не чаще раза в час. Первая загрузка читает два года новостей — около минуты; глубже — <code>ram events --since 2019-01-01</code>.</p>
      </Card>
      {error && <Note kind="warn">{error}</Note>}

      <Card title="Проверка портфелей" sub="Портфели server-analytic-system (акции — пресеты, облигации — последний файл портфелей) и акции отбора портфеля из блоков. «После» — веса без бумаг «продать»: их доля поделена между остальными.">
        {!pfs && <div className="loading"><div className="spinner" /></div>}
        {pfs?.map((pf) => <PortfolioBlock key={pf.key} pf={pf} busy={busy} onStop={toStop} />)}
      </Card>

      <CheckCard />

      <Card title="Стоп-лист" sub={<>Свои исключения: бумага уходит из портфелей с даты записи так же, как по событию «продать». Для того, чего биржа ещё не объявила: оферта о выкупе, слухи о делистинге, решение комитета. <Term k="stoplist">Подробнее</Term>.</>}>
        <StopList items={stop} onSave={saveStop} />
      </Card>

      <Card title="Лента событий" sub="Все решения биржи, которые касаются держателя: новые сверху. Погашения и плановые изменения отсеяны.">
        <FeedTable events={feed} days={days} onDays={setDays} onStop={toStop} busy={busy} />
      </Card>
    </div>
  );
}

function PortfolioBlock({ pf, busy, onStop }: { pf: PortfolioCheck; busy: string; onStop: (code: string, reason: string) => void }) {
  if (pf.error) return <div className="ev-pf"><h4>{pf.title}</h4><p className="hint">Не посчитано: {pf.error}</p></div>;
  const flagged = pf.positions.filter((p) => p.status !== "ok");
  return (
    <div className="ev-pf">
      <h4>{pf.title} {pf.date && <span className="muted">· {day(pf.date)}</span>}</h4>
      <p className="hint">{pf.source} · {pf.positions.length} бумаг ·{" "}
        {flagged.length === 0 ? "событий нет" : <>продать {pf.excluded} ({pct(pf.excluded_weight, 1)} веса), проверить {pf.warned}</>}
        {pf.link && <> · <a href={pf.link}>{pf.excluded ? "открыть без «продать» и пересчитать" : "открыть"}</a></>}</p>
      {flagged.length > 0 && (
        <TableWrap label={pf.title}>
          <table className="compact">
            <thead><tr><th>Бумага</th><th className="r">Вес</th><th className="r">После</th><th className="pl">Статус</th><th>События</th><th /></tr></thead>
            <tbody>{flagged.map((p) => (
              <tr key={p.code}>
                <td><b>{p.name}</b> <span className="muted nowrap">{p.code}</span></td>
                <td className="r">{pct(p.weight, 1)}</td>
                <td className="r">{pct(p.after, 1)}</td>
                <td className="nowrap pl"><StatusTag status={p.status} /></td>
                <td>{p.events.slice(0, 3).map((e, i) => <div key={i}><EventLine e={e} /></div>)}</td>
                <td>{p.status === "warn" && (
                  <button type="button" className="ghost small" disabled={busy === p.code}
                    onClick={() => onStop(p.code, `из проверки портфеля «${pf.title}»: ${p.events[0]?.kind_title ?? ""}`)}>в стоп-лист</button>)}</td>
              </tr>
            ))}</tbody>
          </table>
        </TableWrap>
      )}
      {flagged.length > 0 && pf.excluded! > 0 && (
        <details className="ev-after"><summary>Все веса после исключения</summary>
          <p className="ev-weights">{pf.positions.filter((p) => p.after > 0).sort((a, b) => b.after - a.after)
            .map((p) => `${p.name} ${pct(p.after, 1)}`).join(" · ")}</p>
        </details>
      )}
    </div>
  );
}

function CheckCard() {
  const [text, setText] = useState("");
  const [res, setRes] = useState<CodeCheck[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const go = () => {
    const codes = text.split(/[\s,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
    if (!codes.length) return;
    setBusy(true);
    setError("");
    api.eventsCheck(codes).then((r) => setRes(codes.map((c) => r[c]).filter(Boolean)))
      .catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
  };
  return (
    <Card title="Проверить бумаги" sub="Тикеры акций или ISIN облигаций через запятую или пробел: события по самой бумаге и по её эмитенту.">
      <form className="lab-controls" onSubmit={(e) => { e.preventDefault(); go(); }}>
        <label className="field ev-input"><span>Бумаги</span>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="EUTR, LSRG, SBER, RU000A1061K1" /></label>
        <button type="submit" className="primary" disabled={busy}>{busy ? "Проверяю…" : "Проверить"}</button>
      </form>
      {error && <p className="hint warn-text">{error}</p>}
      {res && (
        <TableWrap label="Проверка бумаг">
          <table className="compact">
            <thead><tr><th>Бумага</th><th>Эмитент</th><th>Статус</th><th>События</th></tr></thead>
            <tbody>{res.map((c) => (
              <tr key={c.code}>
                <td className="nowrap"><b>{c.code}</b> <span className="muted">{c.name}</span></td>
                <td>{c.issuer || <span className="muted">не найден в ISS</span>}</td>
                <td className="nowrap"><StatusTag status={c.status} /></td>
                <td>{c.events.length ? c.events.slice(0, 4).map((e, i) => <div key={i}><EventLine e={e} /></div>) : <span className="muted">—</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        </TableWrap>
      )}
    </Card>
  );
}

function StopList({ items, onSave }: { items: StopItem[]; onSave: (items: StopItem[]) => void }) {
  const [code, setCode] = useState("");
  const [reason, setReason] = useState("");
  return (
    <>
      {items.length > 0 ? (
        <TableWrap label="Стоп-лист">
          <table className="compact">
            <thead><tr><th>Бумага</th><th>С даты</th><th>Причина</th><th /></tr></thead>
            <tbody>{items.map((x) => (
              <tr key={x.code}><td><b>{x.code}</b></td><td className="nowrap">{day(x.date)}</td><td>{x.reason || <span className="muted">—</span>}</td>
                <td><button type="button" className="ghost small" onClick={() => onSave(items.filter((y) => y.code !== x.code))}>убрать</button></td></tr>
            ))}</tbody>
          </table>
        </TableWrap>
      ) : <p className="hint">Пусто.</p>}
      <form className="lab-controls" onSubmit={(e) => {
        e.preventDefault();
        const c = code.trim().toUpperCase();
        if (!c) return;
        onSave([...items.filter((y) => y.code !== c), { code: c, reason: reason.trim(), date: new Date().toISOString().slice(0, 10) }]);
        setCode(""); setReason("");
      }}>
        <label className="field"><span>Тикер или ISIN</span><input value={code} onChange={(e) => setCode(e.target.value)} placeholder="LSRG" /></label>
        <label className="field ev-input"><span>Причина</span><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="ожидается делистинг" /></label>
        <button type="submit" className="ghost">Добавить</button>
      </form>
    </>
  );
}

function FeedTable({ events, days, onDays, onStop, busy }: {
  events: ExchangeEvent[] | null; days: number; onDays: (d: number) => void; onStop: (code: string, reason: string) => void; busy: string;
}) {
  const [level, setLevel] = useState<"" | "exclude" | "warn">("exclude");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [n, setN] = useState(60);
  const kinds = useMemo(() => Array.from(new Set((events ?? []).map((e) => e.kind_title))).sort(), [events]);
  const rows = (events ?? []).filter((e) => (!level || e.level === level) && (!kind || e.kind_title === kind)
    && (!q || (e.issuer + " " + e.codes.join(" ") + " " + e.security).toLowerCase().includes(q.toLowerCase())));
  return (
    <>
      <div className="lab-controls">
        <label className="field"><span>Период</span>
          <select value={days} onChange={(e) => onDays(Number(e.target.value))}>
            {[30, 90, 180, 365, 730].map((d) => <option key={d} value={d}>{d} дней</option>)}
          </select></label>
        <label className="field"><span>Уровень</span>
          <select value={level} onChange={(e) => setLevel(e.target.value as typeof level)}>
            <option value="exclude">продать</option><option value="warn">проверить</option><option value="">все</option>
          </select></label>
        <label className="field"><span>Событие</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">все</option>{kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select></label>
        <label className="field ev-input"><span>Эмитент или код</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ЕвроТранс, EUTR" /></label>
      </div>
      {!events ? <div className="loading"><div className="spinner" /></div> : (
        <TableWrap label="Лента событий">
          <table className="compact">
            <thead><tr><th>Дата</th><th>Статус</th><th>Событие</th><th>Эмитент</th><th>Бумаги</th><th>Причина</th><th /></tr></thead>
            <tbody>{rows.slice(0, n).map((e, i) => (
              <tr key={`${e.id}-${i}`}>
                <td className="nowrap">{day(e.date)}</td>
                <td className="nowrap"><StatusTag status={e.level} /></td>
                <td>{e.kind_title}{e.detail && <span className="muted"> {e.detail}</span>}{e.scope === "issuer" && <span className="muted"> · по эмитенту</span>}</td>
                <td>{e.issuer || <span className="muted">—</span>}</td>
                <td className="nowrap">{e.codes.slice(0, 3).join(", ")}{e.codes.length > 3 && <span className="muted"> +{e.codes.length - 3}</span>}</td>
                <td className="muted">{e.reason.length > 120 ? e.reason.slice(0, 120) + "…" : e.reason}
                  {e.effective && <> · с {day(e.effective)}</>}</td>
                <td className="nowrap">{e.url && <a href={e.url} target="_blank" rel="noreferrer">новость</a>}
                  {e.level === "warn" && e.codes[0] && <> · <button type="button" className="link" disabled={busy === e.codes[0]}
                    onClick={() => onStop(e.codes[0], `${e.kind_title} ${day(e.date)}`)}>в стоп-лист</button></>}</td>
              </tr>
            ))}</tbody>
          </table>
        </TableWrap>
      )}
      {rows.length > n && <button type="button" className="ghost small" onClick={() => setN(rows.length)}>все {rows.length}</button>}
      {events && rows.length === 0 && <p className="hint">Событий с такими условиями нет.</p>}
    </>
  );
}
