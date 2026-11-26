import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent, DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { Theme } from "./theme";
import { day, num, pct } from "./format";
import type { N } from "./api";

echarts.use([LineChart, BarChart, HeatmapChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkLineComponent, VisualMapComponent, AriaComponent, CanvasRenderer]);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Option = Record<string, any>;

export function Chart({ option, height = 320, label }: { option: Option; height?: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.current = c;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); c.dispose(); chart.current = null; };
  }, []);
  useEffect(() => {
    chart.current?.setOption({ aria: { enabled: true, label: { description: label } }, ...option }, { notMerge: true });
  }, [option, label]);
  return <div className="chart" ref={ref} style={{ height }} role="img" aria-label={label} />;
}

const FONT = '"Golos Text", system-ui, -apple-system, "Segoe UI", sans-serif';

export function base(t: Theme): Option {
  return {
    animation: false,
    textStyle: { fontFamily: FONT, color: t.ink2, fontSize: 12 },
    tooltip: {
      trigger: "axis", backgroundColor: t.sheet, borderColor: t.rule, borderWidth: 1, padding: [6, 10],
      textStyle: { color: t.ink, fontSize: 12, fontFamily: FONT }, extraCssText: "box-shadow: 0 4px 14px rgb(0 0 0 / 0.12); border-radius: 6px;",
      axisPointer: { type: "line", lineStyle: { color: t.ink3, width: 1 } },
    },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
  };
}

export function axis(t: Theme, extra: Option = {}): Option {
  return {
    axisLine: { lineStyle: { color: t.rule } }, axisTick: { show: false },
    axisLabel: { color: t.ink3, fontSize: 11, hideOverlap: true },
    splitLine: { lineStyle: { color: t.grid, width: 1 } }, ...extra,
  };
}

export function legend(t: Theme, extra: Option = {}): Option {
  return { top: 0, left: 0, icon: "roundRect", itemWidth: 14, itemHeight: 3, itemGap: 14,
    textStyle: { color: t.ink2, fontSize: 12 }, ...extra };
}

export interface LineSpec { name: string; values: N[]; color: string; width?: number; area?: boolean; dashed?: boolean; z?: number }

function row(name: string, color: string, value: string): string {
  return `<div style="display:flex;justify-content:space-between;gap:14px"><span><i style="display:inline-block;width:10px;height:3px;border-radius:2px;background:${color};margin-right:6px;vertical-align:middle"></i>${name}</span><b style="font-weight:500;font-variant-numeric:tabular-nums">${value}</b></div>`;
}

/** Room above the plot for a legend of these names (wraps at about 80 characters a line). */
export function legendTop(names: string[]): number {
  const chars = names.reduce((n, x) => n + x.length + 5, 0);
  return 14 + 22 * Math.max(1, Math.ceil(chars / 80));
}

/** Lines over dates (a time axis), one y-scale. */
export function timeLines(t: Theme, dates: string[], lines: LineSpec[], o: {
  yFmt?: (v: number) => string; tipFmt?: (v: number) => string; log?: boolean; zoom?: boolean; min?: number; max?: number;
  legend?: boolean; marks?: { date: string; label: string }[];
} = {}): Option {
  const yFmt = o.yFmt ?? ((v: number) => num(v, 2));
  const tipFmt = o.tipFmt ?? yFmt;
  const series = lines.map((l) => ({
    name: l.name, type: "line", showSymbol: false, symbol: "circle", symbolSize: 8, sampling: "lttb", z: l.z ?? 2,
    data: dates.map((d, i) => [d, l.values[i]]), connectNulls: false,
    lineStyle: { color: l.color, width: l.width ?? 2, type: l.dashed ? "dashed" : "solid" }, itemStyle: { color: l.color },
    areaStyle: l.area ? { color: l.color, opacity: 0.14 } : undefined, emphasis: { focus: "series", lineStyle: { width: (l.width ?? 2) + 0.5 } },
    markLine: o.marks && l === lines[0] ? {
      symbol: "none", silent: true, lineStyle: { color: t.ink3, width: 1, type: "solid" },
      label: { color: t.ink3, fontSize: 11, formatter: "{b}", position: "insideEndTop" },
      data: o.marks.map((m) => ({ xAxis: m.date, name: m.label })),
    } : undefined,
  }));
  return {
    ...base(t),
    legend: o.legend === false || lines.length < 2 ? undefined : legend(t, { data: lines.map((l) => l.name) }),
    grid: { left: 8, right: 16, top: lines.length < 2 || o.legend === false ? 16 : legendTop(lines.map((l) => l.name)), bottom: o.zoom ? 44 : 8, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      formatter: (ps: { seriesName: string; value: [string, N]; color: string }[]) => {
        if (!ps.length) return "";
        return `<div style="margin-bottom:4px;color:${t.ink3}">${day(ps[0].value[0])}</div>` +
          ps.filter((p) => p.value[1] !== null && p.value[1] !== undefined)
            .map((p) => row(p.seriesName, p.color, tipFmt(p.value[1] as number))).join("");
      },
    },
    xAxis: axis(t, { type: "time", splitLine: { show: false }, axisLabel: { color: t.ink3, fontSize: 11, hideOverlap: true } }),
    yAxis: axis(t, { type: o.log ? "log" : "value", scale: !o.log, min: o.min, max: o.max,
      axisLabel: { color: t.ink3, fontSize: 11, formatter: yFmt } }),
    dataZoom: o.zoom ? [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "slider", xAxisIndex: 0, height: 22, bottom: 6, borderColor: t.rule, fillerColor: "rgba(127,127,127,0.12)",
        handleStyle: { color: t.sheet, borderColor: t.ink3 }, moveHandleSize: 0, showDetail: false, dataBackground: {
          lineStyle: { color: t.ink3, opacity: 0.5 }, areaStyle: { color: t.ink3, opacity: 0.08 } }, textStyle: { color: t.ink3 } },
    ] : undefined,
    series,
  };
}

/** Grouped bars over categories. */
export function bars(t: Theme, cats: string[], groups: { name: string; values: N[]; color: string }[], o: {
  yFmt?: (v: number) => string; horizontal?: boolean } = {}): Option {
  const yFmt = o.yFmt ?? ((v: number) => pct(v, 0));
  const valueAxis = axis(t, { type: "value", axisLabel: { color: t.ink3, fontSize: 11, formatter: yFmt } });
  const catAxis = axis(t, { type: "category", data: cats, splitLine: { show: false }, axisLabel: { color: t.ink3, fontSize: 11, hideOverlap: true } });
  return {
    ...base(t),
    legend: groups.length > 1 ? legend(t) : undefined,
    grid: { left: 8, right: 16, top: groups.length > 1 ? 40 : 16, bottom: 8, containLabel: true },
    tooltip: { ...base(t).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,0.08)" } },
      formatter: (ps: { seriesName: string; value: N; color: string; name: string }[]) =>
        `<div style="margin-bottom:4px;color:${t.ink3}">${ps[0]?.name ?? ""}</div>` +
        ps.map((p) => row(p.seriesName, p.color, p.value === null ? "–" : yFmt(p.value))).join("") },
    xAxis: o.horizontal ? valueAxis : catAxis,
    yAxis: o.horizontal ? catAxis : valueAxis,
    series: groups.map((g) => ({
      name: g.name, type: "bar", data: g.values, barMaxWidth: 18, barGap: "20%",
      itemStyle: { color: g.color, borderRadius: o.horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0] },
      emphasis: { focus: "series" },
    })),
  };
}

/** A heatmap of values on a diverging blue (positive) - gray - red (negative) scale, the numbers printed in the cells. */
export function heat(t: Theme, xs: string[], ys: string[], values: N[][], o: { fmt?: (v: number) => string; range?: number;
  sequential?: boolean } = {}): Option {
  const fmt = o.fmt ?? ((v: number) => num(v, 2));
  const data: [number, number, N][] = [];
  ys.forEach((_, yi) => xs.forEach((_, xi) => data.push([xi, yi, values[yi]?.[xi] ?? null])));
  const finite = data.map((d) => d[2]).filter((v): v is number => v !== null);
  const range = o.range ?? Math.max(0.1, ...finite.map(Math.abs));
  return {
    ...base(t),
    tooltip: { ...base(t).tooltip, trigger: "item",
      formatter: (p: { value: [number, number, N] }) => `${ys[p.value[1]]} · ${xs[p.value[0]]}<br/><b>${p.value[2] === null ? "–" : fmt(p.value[2])}</b>` },
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: xs, position: "top", axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: t.ink2, fontSize: 11, interval: 0, rotate: xs.length > 8 ? 35 : 0 }, splitArea: { show: false } },
    yAxis: { type: "category", data: ys, inverse: true, axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: t.ink2, fontSize: 11 } },
    visualMap: { show: false, min: o.sequential ? 0 : -range, max: range, dimension: 2,
      inRange: { color: o.sequential ? [t.divMid, t.divPos] : [t.divNeg, t.divMid, t.divPos] } },
    series: [{ type: "heatmap", data, itemStyle: { borderColor: t.sheet, borderWidth: 2, borderRadius: 3 },
      label: { show: true, fontSize: 11, color: t.ink, formatter: (p: { value: [number, number, N] }) => p.value[2] === null ? "" : fmt(p.value[2]) },
      emphasis: { itemStyle: { borderColor: t.ink, borderWidth: 1 } } }],
  };
}
