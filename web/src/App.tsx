import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Meta, type StudyResult } from "./api";
import { Basket } from "./Basket";
import { Overview, Rule, Summary } from "./sec_main";
import { Crises, Scenarios, Tails } from "./sec_risk";
import { Allocation, Drawdown, Regimes, Sizing } from "./sec_more";
import { Theory } from "./Theory";
import { About } from "./About";
import { Factors } from "./Factors";
import { MLPage } from "./MLPage";
import { BookPage } from "./BookPage";
import { HelpPage } from "./HelpPage";
import { EventsPage } from "./EventsPage";
import { AccountPage } from "./AccountPage";
import { EventsNote } from "./eventsUi";
import { Guide } from "./help";
import { DEFAULT_SETTINGS, fromPreset, loadSaved, presetByKey, request, save, type Settings, type UIAsset } from "./state";
import { applyThemeMode, savedThemeMode, type ThemeMode } from "./theme";
import { Note } from "./ui";

const TABS = [
  ["overview", "Обзор", Overview], ["rule", "Правило", Rule], ["crises", "Кризисы", Crises], ["scenarios", "Сценарии", Scenarios],
  ["tails", "Хвосты", Tails], ["drawdown", "Просадка", Drawdown], ["regimes", "Режимы", Regimes],
  ["allocation", "Распределение", Allocation], ["sizing", "Келли и Шарп", Sizing],
] as const;
type Tab = (typeof TABS)[number][0];

function route(): { page: "explore" | "factors" | "ml" | "book" | "account" | "events" | "theory" | "about" | "help"; tab: Tab } {
  const parts = window.location.hash.replace(/^#\/?/, "").split("?")[0].split("/");
  if (parts[0] === "factors") return { page: "factors", tab: "overview" };
  if (parts[0] === "ml") return { page: "ml", tab: "overview" };
  if (parts[0] === "book") return { page: "book", tab: "overview" };
  if (parts[0] === "account") return { page: "account", tab: "overview" };
  if (parts[0] === "help") return { page: "help", tab: "overview" };
  if (parts[0] === "events") return { page: "events", tab: "overview" };
  if (parts[0] === "theory") return { page: "theory", tab: "overview" };
  if (parts[0] === "about") return { page: "about", tab: "overview" };
  const tab = TABS.find((t) => t[0] === parts[1])?.[0] ?? "overview";
  return { page: "explore", tab };
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState("");
  const saved = loadSaved();
  const [assets, setAssets] = useState<UIAsset[]>(saved?.assets ?? []);
  const [settings, setSettings] = useState<Settings>(saved?.settings ?? DEFAULT_SETTINGS);
  const [result, setResult] = useState<{ r: StudyResult; slots: number[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [nav, setNav] = useState(route);
  const [mode, setMode] = useState<ThemeMode>(savedThemeMode);

  useEffect(() => { applyThemeMode(mode); }, [mode]);
  // #/explore/<tab>?preset=<key>[&drop=EUTR,LSRG]: open a ready basket (without the dropped shares) and compute it at once
  const openLinked = (m: Meta): boolean => {
    const q = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
    const linked = q.get("preset") ? presetByKey(m, q.get("preset")!) : undefined;
    if (!linked) return false;
    const s = fromPreset(linked);
    const drop = (q.get("drop") ?? "").split(",").filter(Boolean);
    if (drop.length) s.assets = s.assets.filter((a) => !drop.includes(a.id.split(":").pop() ?? ""));
    setAssets(s.assets);
    setSettings(s.settings);
    setBusy(true);
    setError("");
    api.study(request(s.assets, s.settings)).then((r) => setResult({ r, slots: s.assets.map((x) => x.slot) }))
      .catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
    window.history.replaceState(null, "", window.location.hash.split("?")[0]);  // the link is used once
    return true;
  };
  const metaRef = useRef<Meta | null>(null);
  useEffect(() => {
    const on = () => {
      setNav(route());
      if (metaRef.current && window.location.hash.includes("preset=")) openLinked(metaRef.current);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    api.meta().then((m) => {
      setMeta(m);
      metaRef.current = m;
      if (!openLinked(m) && (!saved || saved.assets.length === 0)) {
        const p = presetByKey(m, "main");
        if (p) { const s = fromPreset(p); setAssets(s.assets); setSettings(s.settings); }
      }
    }).catch((e) => setMetaError((e as Error).message));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { save(assets, settings); }, [assets, settings]);

  const run = useCallback(async (a = assets, s = settings) => {
    setBusy(true);
    setError("");
    try {
      const r = await api.study(request(a, s));
      setResult({ r, slots: a.map((x) => x.slot) });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [assets, settings]);

  const openPreset = (key: string) => {
    const p = presetByKey(meta, key);
    if (!p) return;
    const s = fromPreset(p);
    setAssets(s.assets);
    setSettings(s.settings);
    window.location.hash = "#/";
    run(s.assets, s.settings);
  };

  const Section = TABS.find((t) => t[0] === nav.tab)![2];
  return (
    <div className="app">
      <header className="top">
        <a className="brand" href="#/"><img className="logo" src="/favicon.svg" alt="" />Лаборатория активов</a>
        <nav className="pages" aria-label="Разделы сайта">
          <a href="#/" aria-current={nav.page === "explore" ? "page" : undefined}>Исследование</a>
          <a href="#/factors" aria-current={nav.page === "factors" ? "page" : undefined}>Факторы акций</a>
          <a href="#/ml" aria-current={nav.page === "ml" ? "page" : undefined}>ML-прогноз</a>
          <a href="#/book" aria-current={nav.page === "book" ? "page" : undefined}>Портфель из блоков</a>
          <a href="#/account" aria-current={nav.page === "account" ? "page" : undefined}>Мой счёт</a>
          <a href="#/events" aria-current={nav.page === "events" ? "page" : undefined}>События</a>
          <a href="#/theory" aria-current={nav.page === "theory" ? "page" : undefined}>Теория</a>
          <a href="#/about" aria-current={nav.page === "about" ? "page" : undefined}>Исследование бота</a>
          <a href="#/help" aria-current={nav.page === "help" ? "page" : undefined}>Справка</a>
        </nav>
        <label className="theme">
          <span className="sr">Тема</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as ThemeMode)} aria-label="Тема">
            <option value="system">тема: авто</option>
            <option value="light">светлая</option>
            <option value="dark">тёмная</option>
          </select>
        </label>
      </header>

      {nav.page === "factors" && <Factors />}
      {nav.page === "ml" && <MLPage />}
      {nav.page === "book" && <BookPage />}
      {nav.page === "account" && <AccountPage />}
      {nav.page === "help" && <HelpPage />}
      {nav.page === "events" && <EventsPage />}
      {nav.page === "theory" && <Theory />}
      {nav.page === "about" && <About onOpen={openPreset} />}
      {nav.page === "explore" && (
        <div className="explore">
          <Basket meta={meta} assets={assets} settings={settings} busy={busy} onAssets={setAssets} onSettings={setSettings}
            onPreset={openPreset} onRun={() => run()} />
          <main className="results" aria-busy={busy}>
            {metaError && <Note kind="warn">API не отвечает ({metaError}). Запустите сервер: <code>ram serve</code>.</Note>}
            {error && <Note kind="warn">Не посчиталось: {error}</Note>}
            {!result && !busy && <Intro meta={meta} onOpen={openPreset} />}
            {busy && !result && <Loading />}
            {result && (
              <>
                <Summary r={result.r} slots={result.slots} />
                <EventsNote r={result.r} assets={assets} onAssets={setAssets} onRun={(a) => run(a)} />
                <nav className="tabs" aria-label="Разделы исследования">
                  {TABS.map(([key, label]) => (
                    <a key={key} href={`#/explore/${key}`} aria-current={nav.tab === key ? "page" : undefined}>
                      {key === "rule" && result.r.meta.mode === "portfolio" ? "Портфель" : label}</a>
                  ))}
                  {busy && <span className="tab-busy">пересчитываю…</span>}
                </nav>
                <div className={"section" + (busy ? " stale" : "")}>
                  <Guide id={nav.tab} />
                  <Section r={result.r} slots={result.slots} />
                </div>
              </>
            )}
          </main>
        </div>
      )}
    </div>
  );
}

function Loading() {
  return (
    <div className="loading" role="status">
      <div className="spinner" aria-hidden="true" />
      <p>Считаю: данные, правило, девять контролей просадки, бутстреп, режимы и распределение. Первая загрузка нового актива — до минуты (Мосбиржа отдаёт историю страницами), дальше из кэша.</p>
    </div>
  );
}

function Intro({ meta, onOpen }: { meta: Meta | null; onOpen: (k: string) => void }) {
  return (
    <div className="intro">
      <h1>Исследовать любой актив так же, как основной счёт бота</h1>
      <p className="lede">Соберите корзину (акции и фонды мира, сырьё, валюты, крипта, бумаги и фьючерсы Мосбиржи, курсы ЦБ) и посмотрите, как на ней работает дневной тренд бота: кризисы, сценарии гэпа, хвосты, контроль просадки, режимы, распределение капитала и сколько можно верить Шарпу.</p>
      <div className="presets">
        {meta?.presets.map((p) => (
          <button key={p.key} type="button" className="preset" onClick={() => onOpen(p.key)}>
            <b>{p.title}</b>
            <span>{p.description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
