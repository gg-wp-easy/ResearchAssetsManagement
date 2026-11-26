// The site's API (src/ram/api.py). Numbers are shares (0.1 = 10%); null where a value is undefined.

export type N = number | null;

export interface SearchHit { id: string; code: string; name: string; kind: string; exchange: string; source: string }
export interface SeriesInfo { id: string; name: string; currency: string; source: string; type: string; kind: string;
  first: string; last: string; days: number; last_value: number; note: string }

export interface AssetSpec { id: string; label: string; rub: boolean; carry: string; carry_offset: number; go: number;
  short_cap: number; vol_floor: number; cbr: boolean; weight: number }
export interface ControlDef { name: string; kind: string; limit: number; floor: number; rolling: number; restart: number; start: number }
export interface Preset { key: string; title: string; description: string; assets: Partial<AssetSpec>[];
  params: { risk: number; lookbacks: number[]; signal?: string }; control?: number; history_from?: string; period?: string;
  start?: string }
export interface Meta { presets: Preset[]; controls: ControlDef[]; windows: [string, string, string, string][];
  defaults: Params; carries: Record<string, string> }
export interface Params { risk: number; lookbacks: number[]; slow: number; fast: number; cost: number; band: number;
  margin_cap: number; cbr_scale: number; signal?: string }

export interface StudyRequest { assets: AssetSpec[]; params: Partial<Params>; control: number; period: string;
  start?: string; history_from?: string; money_share: number; windows?: [string, string, string, string][]; bootstrap_paths?: number;
  cov?: string; events?: "exit" | "mark" | "off" }

export interface Perf { cagr: number; mean: number; vol: number; sharpe: number; dd: number; dd_from: string; dd_to: string;
  calmar: number; worst_day: number; worst_day_date: string; worst_month: number; worst_month_date: string;
  worst_year: number; best_year: number; underwater: number; skew: number; kurt: number; years: number; from: string; to: string;
  cut?: number; vs_base?: number; t?: number }
export interface Thin { dates: string[]; values: N[][] }

export interface AssetRow { label: string; cagr: N; vol: N; sharpe: N; dd: N; worst_day: N; worst_day_date: string | null;
  xi_down: N; xi_up: N; hill_down: N; hill_up: N; kurt: N; skew: N; n: number; vol_now: N; w_now: N; full_now: N;
  first: string; last: string }
export interface AssetInfo { id: string; label: string; name: string; source: string; currency: string; native_currency: string;
  type: string; carry: string; carry_offset: number; first: string; last: string; days: number; note: string; stale: boolean }

export interface TailNumbers { xi: N; beta: N; u: N; pu: N; n: number; mean: number; sd: number; kurt: N;
  levels: { q: number; var: N[]; es: N[] }[]; once: { years: number; evt: N; normal: N }[] }

export interface StudyResult {
  meta: { assets: AssetInfo[]; warnings: string[]; params: Params; control: ControlDef; ppy: number; labels: string[];
    mode: "rule" | "portfolio"; bench: string;
    period: { from: string; to: string; years: number; mode: string; calendar_from: string }; elapsed: number;
    events?: StudyEvents };
  overview: { assets: AssetRow[]; curves: Thin; corr: { labels: string[]; full: N[][]; last_year: N[][] } };
  rule: { book: Perf; hold: Perf; vs_hold_t: number; equity: Thin;
    years: { year: string; book: number; hold: N; assets: number[]; costs: number }[];
    worst_months: { month: string; r: number }[]; worst_days: { date: string; r: number; assets: number[] }[];
    positions: Thin; per_asset_year: number[]; turnover: number; costs_year: number;
    lookbacks: { columns: string[]; rows: string[]; sharpe: N[][]; mean: N[][]; current: string } };
  crises: { label: string; from: string; to: string; region: string; traded: boolean; book: N; worst_day: N;
    positions: number[] | null; moves: N[] }[];
  scenarios: { date: string; risk: number; risks: number[]; vol_now: N[]; sigma_day: N[]; full: N[]; weights: number[];
    go: number[]; short_cap: number[]; margin_cap: number; money_share: number;
    historical: { label: string; region: string; moves: N[][] }[]; hypothetical: { label: string; moves: number[] }[] };
  tails: { day: TailNumbers; week: TailNumbers; survival: { empirical: number[][]; gpd: number[][]; normal: number[][]; u: number };
    histogram: { centers: number[]; counts: number[]; normal: number[] };
    assets: (AssetRow & { hill_k: number[]; hill_down_curve: N[]; hill_up_curve: N[] })[]; worst: { date: string; r: number }[] };
  drawdown: { rows: { name: string; control: ControlDef; stats: Perf; chosen: boolean }[]; equity: Thin;
    odds: { name: string; odds: Record<string, Record<string, number>>; median: Record<string, number> }[];
    multipliers: { dd: number[]; curves: { name: string; values: number[] }[] } };
  regimes: { error?: string; dates: string[]; p_bad: number[]; p_bad_smooth: number[]; now: number; labels: string[];
    transition: number[][];
    states: { share: number; duration_weeks: number; mkt_vol: number; assets: { mean: N; vol: N }[]; book_mean: number;
      book_vol: number; book_sharpe: number; avg_corr: N }[] };
  allocation: { error?: string; from: string; to: string; window_weeks: number; hold_weeks: number; labels: string[];
    rows: { key: string; title: string; cagr: number; vol: number; sharpe: number; dd: number; worst_week: number;
      cvar95: number; turnover: N; now: number[] | null }[];
    equity: Thin; history: Record<string, { date: string; w: number[] }[]>; cov: string; shrinkage: N };
  sizing: { kelly: { mu: number; vol: number; sharpe: number; years: number; f_star: number; c_now: number; growth_now: N;
      kelly_vol: number; c_star: number; curve: number[][]; g_star: number };
    significance: { sharpe: number; years: number; se: number; low: number; high: number; t: number;
      luck: { years: number; values: { k: number; sr: number }[] }[]; need: { dsr: number; rho: number; years: number }[] };
    vs_hold: { rho: number; sr_a: number; sr_b: number; diff: number; se: number; t: number; years_needed: N };
    vs_base: { rho: number; sr_a: number; sr_b: number; diff: number; se: number; t: number; years_needed: N } | null };
}

// ---------------------------------------------------------------------------- the factor lab (/api/factors)

export interface FactorRow { key: string; title: string; data: "price" | "dividends" | "reports" | "valuation"; desc: string;
  months: number; from: string; to: string; names: number; ic: number; ic_t: N; ic_hit: number; q: N[]; ew: number;
  ls: number; ls_t: N; ex: number; ex_t: N; net: number; net_t: N; turnover: number; sig: boolean;
  series: { dates: string[]; ends: string[]; ic: N[]; cum: number[][]; net: N[] } }
export interface Parity { day: string; ours: number; theirs: number; common: number; multiple_rho: N; multiple_median_ratio: N;
  analyses: Record<string, { n: number; rho: number }> }
export interface ValuationSummary { dates: string[]; parity: Parity[];
  multiples: Record<string, { label: string; n: N[]; r2: Record<"reg" | "tree" | "nn" | "base", N[]>;
    r2_mean: Record<"reg" | "tree" | "nn" | "base", N>; features: Record<string, number> }> }
export interface FactorLab {
  meta: { from: string; to: string; months: number; top: number; cost: number; start: string; panel_from: string;
    panel_to: string; tickers: number; sas: boolean; warnings: string[]; lost_share: number };
  universe: { dates: string[]; ends: string[]; count: number[]; median_value: number[]; ew: number[]; mcftr: number[]; ew_year: number;
    mcftr_year: number };
  factors: FactorRow[];
  fm: { key: string; title: string; from: string; to: string; months: number; r2: number;
    rows: { key: string; title: string; coef: number; t: N }[] }[];
  corr: { keys: string[]; titles: string[]; values: N[][] };
  testing: { k: number; bonferroni: number; hlz: number; noise_max: number };
  valuation: ValuationSummary | null;
  elapsed: number;
}
export interface MLRow extends FactorRow { set: string; set_title: string; model: string; importance: Record<string, number>;
  inputs: string[]; dsr: { sr: number; sr0: number; trials: number; dsr: number; psr: number; months: number } | Record<string, never> }
export interface MLLab {
  meta: { start: string; top: number; cost: number; refit: number; trials: number; warnings: string[]; panel_to: string };
  sets: { key: string; title: string; inputs: string[]; min_train: number }[];
  models: { key: string; title: string }[];
  rows: MLRow[];
  titles: Record<string, string>;
  elapsed: number;
}
export interface FactorRequest { start: string; top: number; cost: number }

export type EventLevel = "exclude" | "warn";
export interface ExchangeEvent {
  id: number; date: string; kind: string; kind_title: string; level: EventLevel; scope: "issuer" | "security"; title: string;
  issuer: string; security: string; codes: string[]; reason: string; effective: string; detail: string; url: string;
}
export interface EventCoverage { from: string | null; to: string | null; news: number; read: number; checked: number }
export interface CodeCheck { code: string; status: "exclude" | "warn" | "ok"; issuer: string; name: string; events: ExchangeEvent[] }
export interface StudyEvents {
  mode: "exit" | "mark" | "off"; masked: boolean; coverage: EventCoverage | null;
  assets: ({ code: string; status: CodeCheck["status"]; issuer: string; events: ExchangeEvent[]; sold: string | null;
    sold_kind: string | null; sold_news: string | null; sold_url: string | null } | null)[];
  with?: Perf; without?: Perf;
}
export interface PortfolioCheck {
  key: string; title: string; source?: string; date?: string | null; error?: string; link?: string | null;
  excluded?: number; warned?: number; excluded_weight?: number; drop?: string[];
  positions: { code: string; name: string; weight: number; status: CodeCheck["status"]; issuer: string; events: ExchangeEvent[];
    after: number }[];
}
export interface StopItem { code: string; reason: string; date: string }

export type Choice = [string, string];
export interface BookRequest {
  equity: string; bonds: string; trend: string; method: "risk" | "weights"; budget: [number, number, number];
  target_vol: number; limit: number; control: number; cost: number; start: string; events?: boolean;
}
export interface BookRow {
  key: string; title: string; kind: "book" | "sleeve"; cagr: N; vol: N; sharpe: N; dd: N; dd_from: string; dd_to: string;
  worst_week: N; worst_4w: N; years: N; cut_weeks?: N; adjust_weeks?: N; binding?: N; worst_scenario?: N; cash_share?: N; turnover?: N;
}
export interface BookDecision {
  date: string; kind: "rebalance" | "cut" | "adjust" | "event"; w: number[]; ticker?: string; name?: string; event?: string;
  news?: string; url?: string; share?: number; budget_w?: number[]; vol?: N; rc?: number[]; scenario: string;
  loss_before: number; loss_after: number; cut: number[]; m: number; pos: number[]; betas?: number[]; picks?: string[]; added?: string[];
  removed?: string[]; next: N; until: string;
}
export interface BookScenario { label: string; kind: "hyp" | "hist"; to: string; loss: number; sleeves: number[]; moves: number[] }
export interface SharpeDiff { rho: number; sr_a: number; sr_b: number; diff: number; se: number; t: number; years_needed: N }
export interface BookResult {
  meta: {
    opts: Omit<BookRequest, "budget"> & { budget: Record<string, number> }; from: string; to: string; weeks: number;
    panel_to: string; window: number; min_weeks: number; rebalance_cost: number; notes: string[]; control: string;
    events_from: string | null; sales: number;
    choices: { equity: Choice[]; bonds: Choice[]; trend: Choice[]; controls: string[] }; sleeves: string[]; markets: string[];
  };
  rows: BookRow[];
  series: { dates: string[]; equity: Record<string, number[]>; drawdown: Record<string, number[]>; weights: number[][];
    worst: number[]; worst_no_cap: number[] | null };
  years: { year: string; book: N; "6040": N; mcftr: N; cash: N }[];
  tests: { book: { sharpe: number; years: number; se: number; low: number; high: number; t: number } } &
    Record<string, SharpeDiff | Record<string, never>>;
  limits: (BookRow & { limit: number })[];
  corr: { labels: string[]; values: number[][] };
  log: BookDecision[];
  today: { date: string; w: number[]; budget: number[]; decided: string; latest: string; latest_kind: BookDecision["kind"];
    pos: number[]; scenarios: BookScenario[];
    limit: number; picks: { ticker: string; name: string; status: CodeCheck["status"]; sold: boolean; events: ExchangeEvent[] }[];
    picked: string | null; betas: number[] };
  elapsed: number;
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  meta: () => call<Meta>("/api/meta"),
  search: (q: string, signal?: AbortSignal) => call<SearchHit[]>(`/api/search?q=${encodeURIComponent(q)}`, { signal }),
  series: (id: string) => call<SeriesInfo>(`/api/series?id=${encodeURIComponent(id)}`),
  study: (req: StudyRequest) => call<StudyResult>("/api/study", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }),
  factors: (req: FactorRequest) => call<FactorLab>("/api/factors", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }),
  ml: (req: FactorRequest) => call<MLLab>("/api/ml", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }),
  eventsFeed: (days = 90, level?: EventLevel) => call<{ coverage: EventCoverage; events: ExchangeEvent[] }>(
    `/api/events/feed?days=${days}${level ? `&level=${level}` : ""}`),
  eventsCheck: (codes: string[]) => call<Record<string, CodeCheck>>("/api/events/check", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes }) }),
  eventsPortfolios: () => call<{ coverage: EventCoverage; portfolios: PortfolioCheck[] }>("/api/events/portfolios"),
  eventsUpdate: () => call<EventCoverage>("/api/events/update", { method: "POST" }),
  stoplist: () => call<{ items: StopItem[] }>("/api/events/stoplist"),
  saveStoplist: (items: StopItem[]) => call<{ items: StopItem[] }>("/api/events/stoplist", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) }),
  book: (req: BookRequest) => call<BookResult>("/api/book", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }),
};
