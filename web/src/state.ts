import type { AssetSpec, Meta, Preset, SeriesInfo, StudyRequest } from "./api";

export interface UIAsset extends AssetSpec { slot: number; info?: SeriesInfo }

export interface Settings {
  signal: "trend" | "weights";
  risk: number;
  lookbacks: number[];
  fast: number;
  cost: number;
  margin_cap: number;
  control: number;
  period: "common" | "full";
  start: string;
  history_from: string;
  money_share: number;
  windows: [string, string, string, string][];
  cov: "shrunk" | "sample";
  events: boolean;  // sell a MOEX share on the exchange's default / bankruptcy / delisting news
}

export const DEFAULT_SETTINGS: Settings = {
  signal: "trend", cov: "shrunk", risk: 0.10, lookbacks: [20], fast: 20, cost: 0.0006, margin_cap: 0.5, control: 0, period: "common", start: "",
  history_from: "", money_share: 0.5, windows: [], events: true,
};

export const ASSET_DEFAULTS: Omit<AssetSpec, "id" | "label"> = {
  rub: false, carry: "auto", carry_offset: 0, go: 0.1, short_cap: 1, vol_floor: 0, cbr: false, weight: 0,
};

export function freeSlot(assets: UIAsset[]): number {
  const used = new Set(assets.map((a) => a.slot));
  for (let s = 0; s < 8; s++) if (!used.has(s)) return s;
  return -1;
}

export function fromPreset(p: Preset): { assets: UIAsset[]; settings: Settings } {
  const assets: UIAsset[] = [];
  for (const a of p.assets) {
    assets.push({ ...ASSET_DEFAULTS, label: "", ...a, id: a.id!, slot: freeSlot(assets) });
  }
  return {
    assets,
    settings: { ...DEFAULT_SETTINGS, risk: p.params.risk, lookbacks: p.params.lookbacks, control: p.control ?? 0,
      history_from: p.history_from ?? "", period: (p.period as Settings["period"]) ?? "common", start: p.start ?? "",
      signal: p.params.signal === "weights" ? "weights" : "trend" },
  };
}

export function request(assets: UIAsset[], s: Settings): StudyRequest {
  return {
    assets: assets.map(({ slot: _slot, info: _info, ...spec }) => spec),
    params: { risk: s.risk, lookbacks: s.lookbacks, fast: s.fast, cost: s.cost, margin_cap: s.margin_cap, signal: s.signal },
    control: s.control, period: s.period, start: s.start || undefined, history_from: s.history_from || undefined,
    money_share: s.money_share, windows: s.windows.length ? s.windows : undefined, cov: s.cov,
    events: s.events ? "exit" : "mark",
  };
}

const KEY = "ram.basket.v1";

export function loadSaved(): { assets: UIAsset[]; settings: Settings } | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    if (!Array.isArray(v.assets)) return null;
    return { assets: v.assets.map((a: UIAsset) => ({ ...ASSET_DEFAULTS, ...a })), settings: { ...DEFAULT_SETTINGS, ...v.settings } };
  } catch {
    return null;
  }
}

export function save(assets: UIAsset[], settings: Settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ assets: assets.map(({ info: _i, ...a }) => a), settings }));
  } catch { /* storage blocked: the basket is just not remembered */ }
}

export function presetByKey(meta: Meta | null, key: string): Preset | undefined {
  return meta?.presets.find((p) => p.key === key);
}
