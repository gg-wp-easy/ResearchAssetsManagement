import { useEffect, useState } from "react";

// Colours come from CSS custom properties (styles.css), so the charts follow the light / dark switch.
export interface Theme {
  dark: boolean;
  ink: string; ink2: string; ink3: string; rule: string; grid: string; sheet: string; paper: string; accent: string;
  series: string[]; gray: string; good: string; warn: string; bad: string;
  divNeg: string; divMid: string; divPos: string; seq: string[];
}

const SERIES = Array.from({ length: 8 }, (_, i) => `--s${i + 1}`);

function read(): Theme {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string) => cs.getPropertyValue(name).trim();
  const root = document.documentElement.dataset.theme;
  const dark = root === "dark" || (root !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  return {
    dark, ink: v("--ink"), ink2: v("--ink-2"), ink3: v("--ink-3"), rule: v("--rule"), grid: v("--grid"),
    sheet: v("--sheet"), paper: v("--paper"), accent: v("--accent"), series: SERIES.map(v), gray: v("--s-gray"),
    good: v("--good"), warn: v("--warn"), bad: v("--bad"), divNeg: v("--div-neg"), divMid: v("--div-mid"),
    divPos: v("--div-pos"), seq: [v("--seq-1"), v("--seq-2"), v("--seq-3"), v("--seq-4"), v("--seq-5")],
  };
}

let current: Theme | null = null;
const listeners = new Set<(t: Theme) => void>();

function refresh() {
  current = read();
  listeners.forEach((f) => f(current!));
}

if (typeof window !== "undefined") {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", refresh);
  new MutationObserver(refresh).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}

export function useTheme(): Theme {
  const [t, set] = useState<Theme>(() => current ?? (current = read()));
  useEffect(() => {
    listeners.add(set);
    return () => { listeners.delete(set); };
  }, []);
  return t;
}

/** Colour of an asset: its slot in the basket (fixed when added), gray past the eighth. */
export function slotColor(t: Theme, slot: number): string {
  return slot >= 0 && slot < 8 ? t.series[slot] : t.gray;
}

export type ThemeMode = "system" | "light" | "dark";

export function applyThemeMode(mode: ThemeMode) {
  const el = document.documentElement;
  if (mode === "system") delete el.dataset.theme;
  else el.dataset.theme = mode;
  try { localStorage.setItem("ram.theme", mode); } catch { /* storage blocked */ }
}

export function savedThemeMode(): ThemeMode {
  try {
    const m = localStorage.getItem("ram.theme");
    if (m === "light" || m === "dark") return m;
  } catch { /* storage blocked */ }
  return "system";
}
