import { useCallback, useEffect, useState } from "react";
import { api, type Meta, type StudyResult } from "./api";
import { Basket } from "./Basket";
import { Overview, Rule, Summary } from "./sec_main";
import { Crises, Scenarios, Tails } from "./sec_risk";
import { Allocation, Drawdown, Regimes, Sizing } from "./sec_more";
import { Theory } from "./Theory";
import { About } from "./About";
import { Factors } from "./Factors";
import { DEFAULT_SETTINGS, fromPreset, loadSaved, presetByKey, request, save, type Settings, type UIAsset } from "./state";
import { applyThemeMode, savedThemeMode, type ThemeMode } from "./theme";
import { Note } from "./ui";

const TABS = [
  ["overview", "Обзор", Overview], ["rule", "Правило", Rule], ["crises", "Кризисы", Crises], ["scenarios", "Сценарии", Scenarios],
  ["tails", "Хвосты", Tails], ["drawdown", "Просадка", Drawdown], ["regimes", "Режимы", Regimes],
  ["allocation", "Распределение", Allocation], ["sizing", "Келли и Шарп", Sizing],
] as const;
type Tab = (typeof TABS)[number][0];

function route(): { page: "explore" | "factors" | "theory" | "about"; tab: Tab } {
  const parts = window.location.hash.replace(/^#\/?/, "").split("?")[0].split("/");
  if (parts[0] === "factors") return { page: "factors", tab: "overview" };
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
  useEffect(() => {
    const on = () => setNav(route());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    api.meta().then((m) => {
      setMeta(m);
      // #/explore/<tab>?preset=<key>: open a ready basket and compute it at once (a link to share)
      const asked = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("preset");
      const linked = asked ? presetByKey(m, asked) : undefined;
      if (linked) {
        const s = fromPreset(linked);
        setAssets(s.assets);
        setSettings(s.settings);
        setBusy(true);
        api.study(request(s.assets, s.settings)).then((r) => setResult({ r, slots: s.assets.map((x) => x.slot) }))
          .catch((e) => setError((e as Error).message)).finally(() => setBusy(false));
      } else if (!saved || saved.assets.length === 0) {
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
          <a href="#/theory" aria-current={nav.page === "theory" ? "page" : undefined}>Теория</a>
          <a href="#/about" aria-current={nav.page === "about" ? "page" : undefined}>Исследование бота</a>
        </nav>
        <label className="theme">
          <span className="sr">Тема</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as ThemeMode)} aria-label="Тема">
            <option value="system">тема: как в системе</option>
            <option value="light">светлая</option>
            <option value="dark">тёмная</option>
          </select>
        </label>
      </header>

      {nav.page === "factors" && <Factors />}
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
                <nav className="tabs" aria-label="Разделы исследования">
                  {TABS.map(([key, label]) => (
                    <a key={key} href={`#/explore/${key}`} aria-current={nav.tab === key ? "page" : undefined}>
                      {key === "rule" && result.r.meta.mode === "portfolio" ? "Портфель" : label}</a>
                  ))}
                  {busy && <span className="tab-busy">пересчитываю…</span>}
                </nav>
                <div className={"section" + (busy ? " stale" : "")}>
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
