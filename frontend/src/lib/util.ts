import type { Group, Issue, SignalSpec } from "./types";

export const GROUPS: { key: Group; title: string; hint: string; color: string }[] = [
  { key: "property", title: "Свойства", hint: "Что устройство измеряет и сообщает", color: "var(--color-g-property)" },
  { key: "capability", title: "Возможности", hint: "Чем можно управлять из приложения и сценариев", color: "var(--color-g-capability)" },
  { key: "setting", title: "Настройки", hint: "Пороги, таймеры и периоды", color: "var(--color-g-setting)" },
  { key: "environment", title: "Окружение", hint: "Физический мир для эмулятора: вода, дым, люди. На платформу не уходит", color: "var(--color-g-environment)" },
];

export const groupColor = (g: Group) => GROUPS.find((x) => x.key === g)?.color ?? "var(--color-mute)";

const TR: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z", и: "i", й: "y", к: "k", л: "l",
  м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "c", ч: "ch", ш: "sh",
  щ: "sch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
};

/** «Кран на кухне» → kran_na_kuhne (годится для имён Ujin: без дефисов) */
export function slug(text: string, max = 32): string {
  const s = text.toLowerCase().split("").map((c) => TR[c] ?? c).join("")
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^[0-9_]+/, "");
  return s.slice(0, max).replace(/_+$/, "") || "device";
}

/** Двухбуквенный «химический» символ устройства: Датчик протечки → Дп */
export function symbol(title: string): string {
  const words = title.replace(/[^\p{L}\s]/gu, "").split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0].toUpperCase() + words[1][0].toLowerCase());
  const w = words[0] || "?";
  const cons = w.slice(1).match(/[бвгджзклмнпрстфхцчшщbcdfghjklmnpqrstvwxz]/i);
  return w[0].toUpperCase() + (cons ? cons[0].toLowerCase() : (w[1] || ""));
}

export function issuesAt(issues: Issue[], path: string): Issue[] {
  return issues.filter((i) => i.path === path || i.path.startsWith(path + ".") || i.path.startsWith(path + "["));
}

export function exactIssues(issues: Issue[], path: string): Issue[] {
  return issues.filter((i) => i.path === path);
}

export function sigType(s: SignalSpec) {
  return s.type ?? "number";
}

export function fmtValue(s: SignalSpec | undefined, v: unknown): string {
  if (v === undefined || v === null) return "—";
  if (s?.options && String(v) in s.options) return s.options[String(v)];
  if (typeof v === "number") {
    const p = s?.precision ?? 2;
    const txt = Number.isInteger(v) ? String(v) : v.toFixed(Math.min(p, 4)).replace(/\.?0+$/, "");
    return s?.unit ? `${txt} ${s.unit}` : txt;
  }
  return String(v);
}

export function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x));
}
