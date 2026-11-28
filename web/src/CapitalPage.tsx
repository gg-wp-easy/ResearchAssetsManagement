import { useEffect, useMemo, useState } from "react";
import { api, type BookRequest, type CapitalPlan, type CapitalResult } from "./api";
import { Chart, timeLines } from "./charts";
import { day, num, pct } from "./format";
import { Guide, Term } from "./help";
import { useTheme } from "./theme";
import { Card, Note, Segmented, TableWrap, Tile, V } from "./ui";

const ACCOUNT_KEY = "ram.account.v1"; // the book's options of «Мой счёт»: the capital's book is the same
type Opts = Pick<BookRequest, "limit" | "trend" | "equity" | "bonds">;
const OPTS: Opts = { limit: 0.25, trend: "main_guard", equity: "composite", bonds: "own" };
const REGIMES: Record<string, string> = { tight: "ужесточение", hold: "пауза", ease: "смягчение" };

function read<T>(key: string, fallback: T): T {
  try {
    const v = JSON.parse(localStorage.getItem(key) ?? "null");
    return v ?? fallback;
  } catch { return fallback; }
}

const rub = (x: number | null | undefined, sign = false): string => {
  if (typeof x !== "number" || !Number.isFinite(x)) return "—";
  const s = Math.round(Math.abs(x)).toLocaleString("ru-RU") + " ₽";
  return x < 0 ? "−" + s : sign && x > 0 ? "+" + s : s;
};

export function CapitalPage() {
  const [res, setRes] = useState<CapitalResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<string>("");
  const [saved, setSaved] = useState("");
  useEffect(() => {
    setBusy(true);
    const opts = { ...OPTS, ...read<Partial<Opts>>(ACCOUNT_KEY, {}) };
    api.capital(opts).then((r) => { setRes(r); setPlan(r.main); }).catch((e) => setError((e as Error).message))
      .finally(() => setBusy(false));
  }, []);
  const choose = (p: string) => {  // the plan lives in the account's settings: the bot's plan follows it
    setPlan(p);
    setSaved("");
    api.accountSettings().then((st) => api.saveAccountSettings({ ...st, capital_plan: p }))
      .then(() => setSaved(p)).catch((e) => setError((e as Error).message));
  };
  const chosen = res ? (res.plans.find((p) => p.key === plan) ?? res.plans.find((p) => p.key === res.main) ?? res.plans[0]) : null;

  return (
    <div className="lab">
      <header className="lab-head">
        <h1>Весь капитал</h1>
        <p>Счёт с портфелем из блоков, физическое золото, наличная валюта и фонды недвижимости — классы одного портфеля. Несколько планов долей, каждый проверен с 2016 года на тех же неделях, что и портфель из блоков; худшие сценарии на весь капитал и что сделать руками. Выбранный план идёт в план счёта и боту: биржевое золото и валютные облигации — строками заявок.</p>
      </header>
      <Guide id="capital" />
      {error && <Note kind="warn">Не посчиталось: {error}</Note>}
      {!res && busy && <div className="loading"><div className="spinner" /></div>}
      {res && chosen && (
        <div className={busy ? "stale" : ""}>
          <Today r={res} />
          <Plans r={res} chosen={chosen.key} onChoose={choose} />
          {saved && <Note>План «{res.plans.find((p) => p.key === saved)?.title}» сохранён: по нему строится план счёта и выгрузка для бота (таймер ram-plan на сервере — со следующего запуска после push.sh).</Note>}
          <Actions r={res} p={chosen} />
          <Scenarios r={res} p={chosen} />
          <Growth r={res} />
          <Years r={res} />
          <Regime r={res} />
          <Currency r={res} />
          {res.notes.length > 0 && <Note>{res.notes.map((n) => <div key={n}>{n}</div>)}</Note>}
        </div>
      )}
    </div>
  );
}

function Today({ r }: { r: CapitalResult }) {
  const outside = r.holdings.length > 1;
  return (
    <Card title={`Капитал на ${day(r.date)}: ${rub(r.total)}`} sub={<>Счёт — деньги на бумаги и на фьючерсы из настроек «Моего счёта»; слитки — по биржевой цене грамма, валюта — по курсу ЦБ, паи — по цене на бирже. {outside ? "" : "Золото, наличную валюту и фонды недвижимости добавь на странице «Мой счёт» — здесь появятся их доли и что с ними делать."}</>}>
      <div className="tiles">
        {r.keys.map((k) => <Tile key={k} label={<Term k="capital_class">{r.titles[k]}</Term>} value={pct(r.shares[k] ?? 0, 0)} sub={rub((r.shares[k] ?? 0) * r.total)} />)}
      </div>
      {outside && (
        <TableWrap label="Состав капитала">
          <table className="compact">
            <thead><tr><th>Что</th><th>Как оценено</th><th className="r">Стоимость</th><th className="r">При продаже</th><th className="r">Доля</th></tr></thead>
            <tbody>
              {r.holdings.map((i) => (
                <tr key={i.label}><td>{i.label}</td><td className="muted">{i.detail ?? ""}</td><td className="r">{rub(i.value)}</td>
                  <td className="r">{rub(i.sale)}</td><td className="r">{pct(i.share, 0)}</td></tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Card>
  );
}

function Plans({ r, chosen, onChoose }: { r: CapitalResult; chosen: string; onChoose: (p: string) => void }) {
  const cell = (x: number | undefined, sign = false) => <V x={x} f={(v) => pct(v, 1, sign)} />;
  return (
    <Card title="Планы" sub={<><Term k="capital_plan">План</Term> выбирает доли классов в конце каждого месяца по тому, что было известно тогда; с {day(r.start)} до {day(r.date)}, до налогов. Худший сценарий — на сегодняшних долях плана и позициях тренда, как <Term k="scenario_cap">предел</Term> портфеля из блоков. Выбери план — по нему ниже действия и сценарии.</>}>
      <TableWrap label="Планы долей">
        <table className="compact">
          <thead><tr><th></th><th>План</th><th className="r"><Term k="cagr">В год</Term></th><th className="r"><Term k="vol">Колебания</Term></th>
            <th className="r"><Term k="sharpe">Шарп</Term></th><th className="r"><Term k="dd">Просадка</Term></th><th className="r">Сделок в год</th>
            <th className="r">Худший сценарий</th>{r.keys.map((k) => <th key={k} className="r">{r.titles[k]}</th>)}</tr></thead>
          <tbody>
            {r.plans.map((p) => (
              <tr key={p.key} className={p.key === chosen ? "pick sel" : "pick"} onClick={() => onChoose(p.key)}>
                <td><input type="radio" name="capital-plan" checked={p.key === chosen} onChange={() => onChoose(p.key)} aria-label={p.title} /></td>
                <td>{p.title}{p.key === r.main ? <span className="muted"> · по умолчанию</span> : ""}</td>
                <td className="r">{cell(p.stats.cagr)}</td><td className="r">{cell(p.stats.vol)}</td>
                <td className="r">{num(p.stats.sharpe, 2)}</td><td className="r">{cell(p.stats.dd)}</td>
                <td className="r">{num(p.trades_year, 1)}</td><td className="r">{pct(p.worst_loss, 1)}</td>
                {r.keys.map((k) => <td key={k} className="r">{pct(p.today[k] ?? 0, 0)}<span className="muted"> ({pct(p.mean[k] ?? 0, 0)})</span></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Доли — сегодня, в скобках — в среднем за историю. Класс без года истории в план не входит. Сделка — когда класс отошёл от цели больше чем на {pct(r.params.band, 0)} капитала; перекладка стоит {pct(r.params.cost, 1)} за сторону (на счёте — биржевое золото и валютные облигации).</p>
      <h4 className="sub-head"><Term k="exposure">Позиция по рынкам</Term> сегодня, доля капитала</h4>
      <TableWrap label="Позиция по рынкам">
        <table className="compact">
          <thead><tr><th>План</th>{Object.entries(r.markets).map(([k, t]) => <th key={k} className="r">{t}</th>)}</tr></thead>
          <tbody>
            {r.plans.map((p) => (
              <tr key={p.key} className={p.key === chosen ? "sel" : ""}><td>{p.title}</td>
                {Object.keys(r.markets).map((k) => <td key={k} className="r"><V x={p.exposure[k]} f={(v) => pct(v, 0, true)} /></td>)}</tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">С позициями тренда портфеля из блоков: его фьючерсы на юань и золото — та же валюта и то же золото, короткий фьючерс на ОФЗ уменьшает облигации. Акции и облигации блоков — через их бету к MCFTR и ОФЗ.</p>
    </Card>
  );
}

function Actions({ r, p }: { r: CapitalResult; p: CapitalPlan }) {
  const items = r.actions[p.key] ?? [];
  return (
    <Card title={`Что сделать руками: «${p.title}»`} sub="План не продаёт слитки и наличную валюту: недостающее он докупает на счёте (биржевое золото, валютные облигации — строки плана счёта и /plan бота), лишнее вне счёта — решение твоё. Портфель из блоков строится на оставшиеся деньги счёта.">
      <ul className="todo">{items.map((a) => <li key={a.cls + a.text}>{a.text}</li>)}</ul>
      {r.fx_issues.length > 0 && (
        <>
          <h4 className="sub-head"><Term k="fx_bond">Валютные облигации</Term> сегодня — самые ликвидные</h4>
          <TableWrap label="Валютные облигации">
            <table className="compact">
              <thead><tr><th>Код</th><th>Выпуск</th><th className="r">Цена, %</th><th className="r">Доходность в валюте</th>
                <th className="r"><Term k="duration">Дюрация</Term>, лет</th><th className="r">До погашения или <Term k="offer">оферты</Term>, лет</th>
                <th className="r">Номинал</th></tr></thead>
              <tbody>
                {r.fx_issues.map((b) => (
                  <tr key={b.secid}><td className="nowrap">{b.secid}</td><td>{b.name}</td><td className="r">{num(b.price, 2)}</td>
                    <td className="r">{pct(b.ytm, 1)}</td><td className="r">{num(b.duration, 1)}</td><td className="r">{num(b.life, 1)}</td>
                    <td className="r">{num(b.face, 0)} {b.group === "fx_cny" ? "¥" : "$"}</td></tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </>
      )}
    </Card>
  );
}

function Scenarios({ r, p }: { r: CapitalResult; p: CapitalPlan }) {
  return (
    <Card title={`Худшие сценарии на весь капитал: «${p.title}»`} sub={<>Те же <Term k="scenario">сценарии</Term>, что держат предел портфеля из блоков ({pct(r.limit, 0)}): что теряет каждый класс при сегодняшних долях плана, доля всего капитала.</>}>
      <TableWrap label="Сценарии на весь капитал">
        <table className="compact">
          <thead><tr><th>Сценарий</th>{r.keys.map((k) => <th key={k} className="r">{r.titles[k]}</th>)}<th className="r">Всего</th></tr></thead>
          <tbody>
            {p.worst.map((s) => (
              <tr key={s.label}>
                <td>{s.label}{s.kind === "hist" && s.to ? <span className="muted"> · до {day(s.to)}</span> : ""}</td>
                {r.keys.map((k) => <td key={k} className="r"><V x={-(s.classes[k] ?? 0)} f={(v) => (Math.abs(v ?? 0) < 5e-4 ? "" : pct(v, 1, true))} /></td>)}
                <td className="r"><b><V x={-s.loss} f={(v) => pct(v, 1, true)} /></b></td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Card>
  );
}

function Growth({ r }: { r: CapitalResult }) {
  const t = useTheme();
  const [view, setView] = useState<"plans" | "classes">("plans");
  const opt = useMemo(() => {
    const keys = view === "plans" ? r.plans.map((p) => p.key) : r.keys.map((k) => `class:${k}`);
    const title = (k: string) => view === "plans" ? (r.plans.find((p) => p.key === k)?.title ?? k) : r.titles[k.slice(6)];
    const lines = keys.filter((k) => r.curves.series[k]).map((k, i) => ({
      name: title(k), values: r.curves.series[k], color: t.series[i % 8], width: k === r.main || k === "class:book" ? 3 : 2 }));
    const all = lines.flatMap((l) => l.values.filter((v): v is number => v !== null));
    return timeLines(t, r.curves.dates, lines, { log: true, yFmt: (v) => num(v, 1), tipFmt: (v) => num(v, 2), zoom: true,
      min: Math.floor(Math.min(...all) * 10) / 10, max: Math.ceil(Math.max(...all) * 2) / 2 });
  }, [t, r, view]);
  return (
    <Card title="Рост рубля" sub="С одного рубля в начале планов; логарифмическая шкала — одинаковый наклон значит одинаковый процент в год.">
      <div className="lab-controls">
        <Segmented label="Что показать" value={view} onChange={setView}
          options={[{ value: "plans", label: "планы" }, { value: "classes", label: "классы по отдельности" }]} />
      </div>
      <Chart option={opt} height={360} label="Рост рубля во всём капитале" />
    </Card>
  );
}

function Years({ r }: { r: CapitalResult }) {
  const cols = [...r.plans.map((p) => ({ k: p.key, t: p.title })), ...r.keys.map((k) => ({ k: `class:${k}`, t: r.titles[k] }))];
  return (
    <Card title="По годам" sub="Доход за календарный год до налогов: планы, затем классы по отдельности.">
      <TableWrap label="Доход по годам">
        <table className="compact">
          <thead><tr><th>Год</th>{cols.map((c) => <th key={c.k} className="r">{c.t}</th>)}</tr></thead>
          <tbody>
            {r.years.map((y) => (
              <tr key={y.year}><td>{y.year}</td>{cols.map((c) => <td key={c.k} className="r">
                {typeof y[c.k] === "number" ? <V x={y[c.k] as number} f={(v) => pct(v, 1, true)} /> : ""}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Card>
  );
}

function Regime({ r }: { r: CapitalResult }) {
  const g = r.regime;
  return (
    <Card title={`Режим ЦБ: ${g.title}`} sub={<><Term k="cbr_regime">Режим</Term> — с {day(g.since)}, ключевая ставка {pct(g.key, 2)}. Бюджеты риска плана «по режиму ЦБ» заданы заранее, не подобраны по истории: пока ставку повышают, рубли платят высокую реальную ставку; когда снижают — рубль обычно слабеет, и золоту с валютой достаётся больше риска.</>}>
      <TableWrap label="Бюджеты риска по режимам">
        <table className="compact">
          <thead><tr><th>Режим</th>{r.keys.map((k) => <th key={k} className="r">{r.titles[k]}</th>)}</tr></thead>
          <tbody>
            {Object.entries(r.budgets).map(([reg, b]) => (
              <tr key={reg} className={reg === g.regime ? "sel" : ""}><td>{REGIMES[reg] ?? reg}{reg === g.regime ? " — сейчас" : ""}</td>
                {r.keys.map((k) => <td key={k} className="r">{pct(b[k] ?? 0, 0)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Бюджет — доля риска, а не капитала: у портфеля из блоков колебания около 4% в год, у золота и валюты — около 20%, поэтому даже 20% риска у счёта — больше половины капитала. Риск считается на ковариации за {r.params.window} недель со сжатием Ледуа–Вольфа.</p>
    </Card>
  );
}

function Currency({ r }: { r: CapitalResult }) {
  const c = r.currency;
  return (
    <Card title="Валюта: наличными или облигациями" sub={<>С {day(c.from)} (первый месяц облигаций в юанях) на одних неделях, в рублях: облигации дают купон в валюте поверх курса. До налогов; «после налога» — с налогом 13% с купонов, налог с роста курса при продаже сюда не входит.</>}>
      <TableWrap label="Валюта наличными или облигациями">
        <table className="compact">
          <thead><tr><th>Как держать</th><th className="r">В год</th><th className="r">После налога</th><th className="r">Колебания</th><th className="r">Просадка</th></tr></thead>
          <tbody>
            {c.rows.map((x) => (
              <tr key={x.key}><td>{x.title}</td><td className="r"><V x={x.stats.cagr} f={(v) => pct(v, 1, true)} /></td>
                <td className="r"><V x={x.tax?.cagr} f={(v) => pct(v, 1, true)} /></td><td className="r">{pct(x.stats.vol, 1)}</td>
                <td className="r">{pct(x.stats.dd, 1)}</td></tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="foot">Облигации отобраны так же, как рублёвые: торги не реже 3 недель из 4, цена от 85% номинала, доходность в валюте ниже 20%, эмитент без дефолтов, до погашения или оферты от полугода; один выпуск на эмитента, до 12 самых ликвидных. Наличные вне банка не платят ничего, но и не зависят от брокера и биржи.</p>
    </Card>
  );
}
