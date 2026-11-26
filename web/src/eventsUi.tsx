import { useState } from "react";
import { api, type ExchangeEvent, type StopItem, type StudyResult } from "./api";
import { day, pct } from "./format";
import { Term } from "./help";
import type { UIAsset } from "./state";

/** The status of a security as a tag: what to do, not a colour alone. */
export function StatusTag({ status }: { status: "exclude" | "warn" | "ok" }) {
  if (status === "ok") return <span className="ev-tag ok">нет событий</span>;
  return status === "exclude"
    ? <span className="ev-tag exclude">⛔ продать</span>
    : <span className="ev-tag warn">⚠ проверить</span>;
}

/** One event: date, kind, the reason, a link to the exchange's news. */
export function EventLine({ e, issuer = false }: { e: ExchangeEvent; issuer?: boolean }) {
  return (
    <span className="ev-line">
      <span className="nowrap">{day(e.date)}</span> · <b>{e.kind_title}</b>{e.detail && <> {e.detail}</>}
      {issuer && e.issuer && <> · {e.issuer}</>}
      {e.reason && !e.detail && <span className="muted"> — {e.reason.length > 140 ? e.reason.slice(0, 140) + "…" : e.reason}</span>}
      {e.scope === "issuer" && <span className="muted"> (по эмитенту)</span>}
      {e.url && <> · <a href={e.url} target="_blank" rel="noreferrer">новость</a></>}
    </span>
  );
}

export async function addToStoplist(code: string, reason: string): Promise<StopItem[]> {
  const cur = (await api.stoplist()).items.filter((x) => x.code !== code);
  return (await api.saveStoplist([...cur, { code, reason, date: new Date().toISOString().slice(0, 10) }])).items;
}

/** Under the summary of a study: the basket's MOEX shares with exchange events, what the filter did, the actions. */
export function EventsNote({ r, assets, onAssets, onRun }: {
  r: StudyResult; assets: UIAsset[]; onAssets: (a: UIAsset[]) => void; onRun: (a: UIAsset[]) => void;
}) {
  const ev = r.meta.events;
  const [busy, setBusy] = useState("");
  if (!ev || !ev.assets.some((a) => a && a.status !== "ok")) return null;
  const rows = ev.assets.map((a, j) => ({ a, j, label: r.meta.labels[j] })).filter((x) => x.a && x.a.status !== "ok");
  const excludeIds = new Set(rows.filter((x) => x.a!.status === "exclude").map((x) => r.meta.assets[x.j]?.id));
  const drop = () => {
    const next = assets.filter((a) => !excludeIds.has(a.id));
    onAssets(next);
    onRun(next);
  };
  const stop = async (code: string, label: string) => {
    setBusy(code);
    try { await addToStoplist(code, `добавлено со страницы исследования (${label})`); onRun(assets); } finally { setBusy(""); }
  };
  const w = ev.with, wo = ev.without;
  return (
    <div className="ev-note" role="region" aria-label="События Мосбиржи по бумагам корзины">
      <div className="ev-note-head">
        <b><Term k="exchange_event">События Мосбиржи</Term></b>
        <span className="muted">
          {ev.mode === "exit" ? " — бумага с событием «продать» выходит из портфеля на следующий торговый день после новости" : " — только отметки, без продажи (включите в корзине)"}
          {ev.coverage?.from && <> · лента с {day(ev.coverage.from)}</>}
        </span>
      </div>
      <ul>
        {rows.map(({ a, label }) => (
          <li key={a!.code}>
            <div className="ev-head"><StatusTag status={a!.status} /> <b>{label}</b> <span className="muted">{a!.code}</span>
              {a!.sold && <span> · продан {day(a!.sold)} ({a!.sold_kind})</span>}</div>
            <div className="ev-events">{a!.events.slice(0, 3).map((e, i) => <div key={i}><EventLine e={e} /></div>)}</div>
            {a!.status === "warn" && (
              <button type="button" className="ghost small" disabled={busy === a!.code} onClick={() => stop(a!.code, label)}>
                {busy === a!.code ? "добавляю…" : "в стоп-лист и пересчитать"}</button>
            )}
          </li>
        ))}
      </ul>
      {w && wo && (
        <p className="foot">С продажей по событиям: {pct(w.cagr, 1, true)} в год, Шарп {w.sharpe.toFixed(2).replace(".", ",")}, просадка {pct(w.dd, 1)};
          без неё: {pct(wo.cagr, 1, true)}, Шарп {wo.sharpe.toFixed(2).replace(".", ",")}, просадка {pct(wo.dd, 1)}. Эталон «держать / поровну» тоже продаёт.</p>
      )}
      {excludeIds.size > 0 && (
        <button type="button" className="primary small" onClick={drop}>Убрать отмеченные «продать» из корзины ({excludeIds.size}) и пересчитать</button>
      )}
    </div>
  );
}
