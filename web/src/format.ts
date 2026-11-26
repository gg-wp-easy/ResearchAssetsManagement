// Russian number formats: a comma for decimals, a real minus sign.

const nf = (d: number) => new Intl.NumberFormat("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });
const cache = new Map<number, Intl.NumberFormat>();
function fmt(x: number, d: number): string {
  let f = cache.get(d);
  if (!f) { f = nf(d); cache.set(d, f); }
  return f.format(x).replace("-", "−");
}

export const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** 0.171 -> "17,1%"; sign: "+17,1%". */
export function pct(x: number | null | undefined, d = 1, sign = false): string {
  if (!isNum(x)) return "–";
  const s = fmt(x * 100, d) + "%";
  return sign && x > 0 ? "+" + s : s;
}

export function num(x: number | null | undefined, d = 2, sign = false): string {
  if (!isNum(x)) return "–";
  const s = fmt(x, d);
  return sign && x > 0 ? "+" + s : s;
}

export function years(x: number | null | undefined): string {
  if (!isNum(x)) return "–";
  if (x >= 100) return "больше 100 лет";
  return `${fmt(x, x < 10 ? 1 : 0)} ${plural(Math.round(x), "год", "года", "лет")}`;
}

export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

/** "2026-11-26" -> "26.11.2026". */
export function day(d: string | null | undefined): string {
  if (!d) return "–";
  const [y, m, dd] = d.split("-");
  return dd ? `${dd}.${m}.${y}` : d;
}

export function month(d: string): string {
  const names = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const [y, m] = d.split("-");
  return `${names[Number(m) - 1]} ${y}`;
}

/** Tone of a value for text: good / bad / neutral (the sign carries the meaning, the colour only helps). */
export function tone(x: number | null | undefined, eps = 0): string {
  if (!isNum(x)) return "";
  return x > eps ? "pos" : x < -eps ? "neg" : "";
}
