import type { ReactNode } from "react";
import { slotColor, useTheme } from "./theme";

export function Card({ title, sub, children, id }: { title?: string; sub?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="card" id={id}>
      {title && <h3 className="card-title">{title}</h3>}
      {sub && <p className="card-sub">{sub}</p>}
      {children}
    </section>
  );
}

export function Tile({ label, value, sub, toneClass }: { label: string; value: string; sub?: ReactNode; toneClass?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className={"tile-value " + (toneClass ?? "")}>{value}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}

export function Note({ children, kind = "info" }: { children: ReactNode; kind?: "info" | "warn" | "book" }) {
  return <div className={"note note-" + kind}>{children}</div>;
}

export function Swatch({ slot }: { slot: number }) {
  const t = useTheme();
  return <i className="swatch" style={{ background: slotColor(t, slot) }} aria-hidden="true" />;
}

export function AssetName({ label, slot }: { label: string; slot: number }) {
  return <span className="asset-name"><Swatch slot={slot} />{label}</span>;
}

export function TableWrap({ children, label }: { children: ReactNode; label?: string }) {
  return <div className="tablewrap" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}

/** A signed share as text with its tone; the sign carries the meaning, the colour only helps. */
export function V({ x, f, eps = 0 }: { x: number | null | undefined; f: (x: number | null | undefined) => string; eps?: number }) {
  const cls = typeof x === "number" ? (x > eps ? "pos" : x < -eps ? "neg" : "") : "";
  return <span className={cls}>{f(x)}</span>;
}

export function Segmented<T extends string | number>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} className={o.value === value ? "on" : ""}
          onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}
