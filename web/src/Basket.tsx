import { useEffect, useRef, useState } from "react";
import { api, type Meta, type SearchHit } from "./api";
import { ASSET_DEFAULTS, freeSlot, type Settings, type UIAsset } from "./state";
import { day, num, pct } from "./format";
import { slotColor, useTheme } from "./theme";

const WINDOWS = [10, 20, 40, 60, 120, 250];

export function Basket(props: {
  meta: Meta | null; assets: UIAsset[]; settings: Settings; busy: boolean;
  onAssets: (a: UIAsset[]) => void; onSettings: (s: Settings) => void; onPreset: (key: string) => void; onRun: () => void;
}) {
  const { meta, assets, settings, onAssets, onSettings } = props;
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => onSettings({ ...settings, [k]: v });

  return (
    <aside className="side" aria-label="Корзина и параметры">
      <section className="panel">
        <h2 className="panel-title">Корзина</h2>
        <label className="field">
          <span>Готовый набор</span>
          <select value="" onChange={(e) => e.target.value && props.onPreset(e.target.value)}>
            <option value="">выбрать…</option>
            {meta?.presets.map((p) => <option key={p.key} value={p.key}>{p.title}</option>)}
          </select>
        </label>
        <Search assets={assets} onAdd={(a) => onAssets([...assets, a])} />
        {assets.length === 0 && <p className="hint">Найдите актив по названию или коду (SBER, GLD, BTC-USD, BR, юань) либо выберите готовый набор.</p>}
        <ol className="assets">
          {assets.map((a, i) => (
            <AssetRow key={a.id + i} a={a} meta={meta}
              onChange={(next) => onAssets(assets.map((x, k) => (k === i ? next : x)))}
              onRemove={() => onAssets(assets.filter((_, k) => k !== i))}
              onUp={i > 0 ? () => { const n = [...assets]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; onAssets(n); } : undefined} />
          ))}
        </ol>
      </section>

      <section className="panel">
        <h2 className="panel-title">Правило тренда</h2>
        <div className="grid2">
          <NumField label="Риск на актив" value={settings.risk * 100} step={0.5} min={0.5} max={100} suffix="%"
            onChange={(v) => set("risk", v / 100)} hint="годовая волатильность полной позиции, доля капитала" />
          <label className="field">
            <span>Быстрая волатильность</span>
            <select value={settings.fast} onChange={(e) => set("fast", Number(e.target.value))}>
              <option value={0}>нет (только 60 дн.)</option>
              <option value={10}>10 дней</option>
              <option value={20}>20 дней (бот)</option>
            </select>
          </label>
        </div>
        <div className="field">
          <span>Окна тренда, дней <small>(несколько — среднее силы)</small></span>
          <div className="chips" role="group" aria-label="Окна тренда">
            {WINDOWS.map((w) => {
              const on = settings.lookbacks.includes(w);
              return (
                <button key={w} type="button" className={"chip" + (on ? " on" : "")} aria-pressed={on}
                  onClick={() => {
                    const next = on ? settings.lookbacks.filter((x) => x !== w) : [...settings.lookbacks, w].sort((a, b) => a - b);
                    if (next.length) set("lookbacks", next);
                  }}>{w}</button>
              );
            })}
          </div>
        </div>
        <label className="field">
          <span>Контроль просадки</span>
          <select value={settings.control} onChange={(e) => set("control", Number(e.target.value))}>
            {meta?.controls.map((c, i) => <option key={i} value={i}>{c.name}</option>)}
          </select>
        </label>
        <details className="more">
          <summary>Издержки, ГО, период</summary>
          <div className="grid2">
            <NumField label="Комиссия за сделку" value={settings.cost * 100} step={0.01} min={0} max={2} suffix="%"
              onChange={(v) => set("cost", v / 100)} hint="за изменение позиции, доля номинала" />
            <NumField label="Предел ГО" value={settings.margin_cap * 100} step={5} min={0} max={100} suffix="%"
              onChange={(v) => set("margin_cap", v / 100)} hint="всё ГО не больше доли капитала; 0 — без предела" />
            <NumField label="Деньги на брокерском счёте" value={settings.money_share * 100} step={5} min={5} max={100} suffix="%"
              onChange={(v) => set("money_share", v / 100)} hint="доля суммы для торговли; для сценариев" />
            <label className="field">
              <span>Период статистики</span>
              <select value={settings.period} onChange={(e) => set("period", e.target.value as Settings["period"])}>
                <option value="common">общий для всех активов</option>
                <option value="full">с начала каждого актива</option>
              </select>
            </label>
            <label className="field">
              <span>Начало не раньше</span>
              <input type="date" value={settings.start} onChange={(e) => set("start", e.target.value)} />
            </label>
            <label className="field">
              <span>История с</span>
              <input type="date" value={settings.history_from} onChange={(e) => set("history_from", e.target.value)} />
            </label>
          </div>
        </details>
      </section>

      <div className="run">
        <button type="button" className="primary" disabled={props.busy || assets.length === 0} onClick={props.onRun}>
          {props.busy ? "Считаю…" : "Посчитать"}
        </button>
        <span className="hint">{assets.length ? `${assets.length} ${assets.length === 1 ? "актив" : assets.length < 5 ? "актива" : "активов"}` : ""}</span>
      </div>
    </aside>
  );
}

function Search({ assets, onAdd }: { assets: UIAsset[]; onAdd: (a: UIAsset) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<"" | "loading" | "error">("");
  const [active, setActive] = useState(0);
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const query = q.trim();
    if (query.length < 2) { setHits([]); setState(""); return; }
    const ctl = new AbortController();
    const timer = setTimeout(() => {
      setState("loading");
      api.search(query, ctl.signal).then((h) => { setHits(h); setActive(0); setState(""); setOpen(true); })
        .catch((e) => { if (e.name !== "AbortError") setState("error"); });
    }, 300);
    return () => { clearTimeout(timer); ctl.abort(); };
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  async function add(h: SearchHit) {
    setAdding(h.id);
    setError("");
    try {
      const info = await api.series(h.id);
      const isRub = info.currency === "RUB";
      onAdd({ ...ASSET_DEFAULTS, id: h.id, label: shortLabel(h), info, slot: freeSlot(assets),
        cbr: isRub && (info.type === "currency" || h.id.startsWith("cbr:")) });
      setQ(""); setHits([]); setOpen(false);
    } catch (e) {
      setError(`${h.code}: ${(e as Error).message}`);
    } finally {
      setAdding(null);
    }
  }

  return (
    <div className="search" ref={box}>
      <label className="field">
        <span>Добавить актив</span>
        <input type="search" value={q} placeholder="SBER, золото, BTC-USD, BR, юань…" autoComplete="off"
          role="combobox" aria-expanded={open} aria-controls="search-list"
          onChange={(e) => setQ(e.target.value)} onFocus={() => hits.length && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { setActive((a) => Math.min(a + 1, hits.length - 1)); e.preventDefault(); }
            if (e.key === "ArrowUp") { setActive((a) => Math.max(a - 1, 0)); e.preventDefault(); }
            if (e.key === "Enter" && hits[active]) add(hits[active]);
            if (e.key === "Escape") setOpen(false);
          }} />
      </label>
      {state === "loading" && <div className="hint">ищу в Yahoo, Мосбирже и ЦБ…</div>}
      {state === "error" && <div className="err">поиск не ответил</div>}
      {error && <div className="err">{error}</div>}
      {open && hits.length > 0 && (
        <ul className="hits" id="search-list" role="listbox">
          {hits.map((h, i) => (
            <li key={h.id} role="option" aria-selected={i === active} className={i === active ? "active" : ""}
              onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); add(h); }}>
              <span className={"src src-" + srcClass(h.source)}>{h.source}</span>
              <span className="hit-main"><b>{h.code}</b> {h.name}</span>
              <span className="hit-kind">{adding === h.id ? "загружаю…" : [h.kind, h.exchange].filter(Boolean).join(" · ")}</span>
            </li>
          ))}
        </ul>
      )}
      {open && state === "" && q.trim().length >= 2 && hits.length === 0 && <div className="hint">ничего не найдено</div>}
    </div>
  );
}

function srcClass(s: string) {
  return s === "Yahoo" ? "y" : s === "ЦБ" ? "c" : "m";
}

function shortLabel(h: SearchHit): string {
  const n = h.name || h.code;
  return n.length > 28 ? h.code : n;
}

function AssetRow({ a, meta, onChange, onRemove, onUp }: {
  a: UIAsset; meta: Meta | null; onChange: (a: UIAsset) => void; onRemove: () => void; onUp?: () => void;
}) {
  const t = useTheme();
  const [open, setOpen] = useState(false);
  const set = <K extends keyof UIAsset>(k: K, v: UIAsset[K]) => onChange({ ...a, [k]: v });
  const foreign = a.info ? a.info.currency !== "RUB" : !a.id.startsWith("moex:") && !a.id.startsWith("cbr:");
  return (
    <li className="asset">
      <div className="asset-head">
        <i className="swatch" style={{ background: slotColor(t, a.slot) }} aria-hidden="true" />
        <input className="asset-label" value={a.label} aria-label="Название" placeholder={a.id}
          onChange={(e) => set("label", e.target.value)} />
        <button type="button" className="icon" aria-expanded={open} aria-label="Настройки актива" title="Настройки"
          onClick={() => setOpen(!open)}>{open ? "▴" : "▾"}</button>
        {onUp && <button type="button" className="icon" aria-label="Выше" title="Выше" onClick={onUp}>↑</button>}
        <button type="button" className="icon" aria-label="Убрать" title="Убрать" onClick={onRemove}>×</button>
      </div>
      <div className="asset-sub">
        <code>{a.id}</code>
        {a.info && <span> · {day(a.info.first)}–{day(a.info.last)}{a.info.currency !== "RUB" ? ` · ${a.info.currency}` : ""}</span>}
        {(a.short_cap < 1 || a.rub || a.cbr || a.carry_offset !== 0) && (
          <span className="tags">
            {a.rub && <em>в рублях</em>}
            {a.short_cap === 0 ? <em>только лонг</em> : a.short_cap < 1 && <em>шорт ≤ {num(a.short_cap, 2)}</em>}
            {a.cbr && <em>ЦБ</em>}
            {a.carry_offset !== 0 && <em>ставка {pct(a.carry_offset, 1, true)}</em>}
          </span>
        )}
      </div>
      {open && (
        <div className="asset-more">
          {foreign && (
            <label className="check"><input type="checkbox" checked={a.rub} onChange={(e) => set("rub", e.target.checked)} />
              в рубли по курсу ЦБ</label>
          )}
          <div className="grid2">
            <label className="field">
              <span>Лонг платит</span>
              <select value={a.carry} onChange={(e) => set("carry", e.target.value)}>
                {Object.entries(meta?.carries ?? { auto: "по валюте" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <NumField label="Поправка ставки" value={a.carry_offset * 100} step={0.5} min={-30} max={30} suffix="%"
              onChange={(v) => set("carry_offset", v / 100)} hint="−2,5% у юаня; −8% ≈ дивиденды акции" />
            <NumField label="ГО" value={a.go * 100} step={1} min={0} max={100} suffix="%" onChange={(v) => set("go", v / 100)}
              hint="гарантийное обеспечение, доля номинала" />
            <label className="field">
              <span>Шорт</span>
              <select value={a.short_cap} onChange={(e) => set("short_cap", Number(e.target.value))}>
                <option value={1}>без ограничения</option>
                <option value={0.5}>не больше половины</option>
                <option value={0.25}>не больше четверти</option>
                <option value={0}>только лонг</option>
              </select>
            </label>
            <NumField label="Пол волатильности" value={a.vol_floor * 100} step={1} min={0} max={100} suffix="%"
              onChange={(v) => set("vol_floor", v / 100)} hint="размер не считается от меньшей волатильности" />
            <label className="check"><input type="checkbox" checked={a.cbr} onChange={(e) => set("cbr", e.target.checked)} />
              половина позиции накануне решения ЦБ</label>
          </div>
          {a.info?.note && <p className="hint">{a.info.note}</p>}
        </div>
      )}
    </li>
  );
}

export function NumField({ label, value, onChange, step, min, max, suffix, hint }: {
  label: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number; suffix?: string; hint?: string;
}) {
  const [text, setText] = useState(String(round(value)));
  useEffect(() => setText(String(round(value))), [value]);
  return (
    <label className="field" title={hint}>
      <span>{label}</span>
      <span className="num-input">
        <input type="number" inputMode="decimal" value={text} step={step} min={min} max={max}
          onChange={(e) => {
            setText(e.target.value);
            const v = Number(e.target.value.replace(",", "."));
            if (Number.isFinite(v) && v >= min && v <= max) onChange(v);
          }} />
        {suffix && <span className="suffix">{suffix}</span>}
      </span>
    </label>
  );
}

function round(v: number) {
  return Math.round(v * 10000) / 10000;
}
