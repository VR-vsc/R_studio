import { useEffect, useState } from "react";
import type { Issue } from "../lib/types";

export function IssueText({ issues }: { issues: Issue[] }) {
  if (!issues.length) return null;
  return (
    <div className="mt-1 space-y-0.5">
      {issues.map((i, k) => (
        <p key={k} className={`text-[12.5px] ${i.severity === "error" ? "text-bad" : i.severity === "warning" ? "text-warn" : "text-mute"}`}>
          {i.message}
        </p>
      ))}
    </div>
  );
}

export function Labeled({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12.5px] font-medium text-mute">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[12px] text-mute">{hint}</span>}
    </label>
  );
}

/** Число с пустым значением = null; текст хранится локально, чтобы можно было набрать «1.» */
export function NumInput({ value, onChange, placeholder, className = "", label, disabled }: {
  value: number | null | undefined; onChange: (v: number | null) => void; placeholder?: string; className?: string; label?: string; disabled?: boolean;
}) {
  const [text, setText] = useState(value ?? "" as number | string);
  useEffect(() => {
    const n = Number(String(text).replace(",", "."));
    if ((value ?? null) !== (String(text) === "" ? null : n)) setText(value ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input className={`field tabular-nums ${className}`} inputMode="decimal" aria-label={label}
      value={text} placeholder={placeholder} disabled={disabled}
      onChange={(e) => {
        setText(e.target.value);
        const raw = e.target.value.replace(",", ".");
        if (raw === "" || raw === "-") return onChange(null);
        const n = Number(raw);
        if (!Number.isNaN(n)) onChange(n);
      }} />
  );
}
