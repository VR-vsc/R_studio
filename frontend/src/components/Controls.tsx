import { useEffect, useState } from "react";
import type { SignalSpec } from "../lib/types";
import { fmtValue } from "../lib/util";

type Send = (value: number | string) => void;

/** Пульт для одного сигнала: тумблер, варианты, ползунок, число, кнопка. */
export function Control({ s, value, onSend, tone }: { s: SignalSpec; value: unknown; onSend: Send; tone: string }) {
  const type = s.type ?? "number";
  if (type === "button") {
    return (
      <button className="btn w-full justify-center py-1.5 text-[13px]" style={{ borderColor: tone, color: tone }} onClick={() => onSend(1)}>
        {s.title}
      </button>
    );
  }
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="min-w-0 text-[13.5px] leading-tight">{s.title}</span>
      <div className="shrink-0">
        {type === "bool" ? <Toggle s={s} on={Number(value) === 1} onSend={onSend} tone={tone} />
          : type === "enum" ? <Segmented s={s} value={Number(value)} onSend={onSend} tone={tone} />
            : type === "text" ? <TextSet value={String(value ?? "")} onSend={onSend} />
              : s.min != null && s.max != null && s.max - s.min <= 10000
                ? <Range s={s} value={Number(value)} onSend={onSend} tone={tone} />
                : <NumberSet s={s} value={Number(value)} onSend={onSend} />}
      </div>
    </div>
  );
}

function Toggle({ s, on, onSend, tone }: { s: SignalSpec; on: boolean; onSend: Send; tone: string }) {
  const label = s.options?.[on ? "1" : "0"] ?? (on ? "вкл" : "выкл");
  return (
    <button role="switch" aria-checked={on} aria-label={s.title} onClick={() => onSend(on ? 0 : 1)}
      className="flex items-center gap-2 text-[12.5px] text-mute">
      <span className="w-[86px] text-right">{label}</span>
      <span className="relative h-[22px] w-[40px] rounded-full transition-colors" style={{ background: on ? tone : "var(--color-line)" }}>
        <span className={`absolute top-[3px] h-4 w-4 rounded-full bg-white shadow transition-[left] ${on ? "left-[21px]" : "left-[3px]"}`} />
      </span>
    </button>
  );
}

function Segmented({ s, value, onSend, tone }: { s: SignalSpec; value: number; onSend: Send; tone: string }) {
  const opts = Object.entries(s.options ?? {});
  if (opts.length > 4) {
    return (
      <select className="field w-auto py-1 text-[13px]" value={value} aria-label={s.title} onChange={(e) => onSend(Number(e.target.value))}>
        {opts.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
    );
  }
  return (
    <div className="flex rounded-md border border-line bg-white p-0.5" role="radiogroup" aria-label={s.title}>
      {opts.map(([k, v]) => {
        const on = Number(k) === value;
        return (
          <button key={k} role="radio" aria-checked={on} onClick={() => onSend(Number(k))}
            className="rounded px-2 py-0.5 text-[12.5px]" style={on ? { background: tone, color: "white" } : { color: "var(--color-mute)" }}>
            {v}
          </button>
        );
      })}
    </div>
  );
}

function Range({ s, value, onSend, tone }: { s: SignalSpec; value: number; onSend: Send; tone: string }) {
  const [local, setLocal] = useState(value);
  const [drag, setDrag] = useState(false);
  useEffect(() => { if (!drag) setLocal(value); }, [value, drag]);
  const span = (s.max! - s.min!);
  const step = s.precision === 0 || span >= 50 ? 1 : span / 100;
  const commit = () => { setDrag(false); if (local !== value) onSend(local); };
  return (
    <div className="flex items-center gap-2">
      <input type="range" min={s.min!} max={s.max!} step={step} value={local} aria-label={s.title}
        className="w-[110px]" style={{ accentColor: tone }}
        onPointerDown={() => setDrag(true)} onPointerUp={commit} onKeyUp={commit}
        onChange={(e) => setLocal(Number(e.target.value))} />
      <span className="w-[68px] text-right text-[12.5px] tabular-nums">{fmtValue(s, local)}</span>
    </div>
  );
}

function NumberSet({ s, value, onSend }: { s: SignalSpec; value: number; onSend: Send }) {
  const [text, setText] = useState(String(value));
  const [edit, setEdit] = useState(false);
  useEffect(() => { if (!edit) setText(String(value)); }, [value, edit]);
  const commit = () => {
    setEdit(false);
    const n = Number(text.replace(",", "."));
    if (!Number.isNaN(n) && n !== value) onSend(n);
  };
  return (
    <span className="flex items-center gap-1">
      <input className="field w-[86px] py-1 text-right tabular-nums" value={text} aria-label={s.title}
        onFocus={() => setEdit(true)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        onChange={(e) => setText(e.target.value)} />
      {s.unit && <span className="text-[12.5px] text-mute">{s.unit}</span>}
    </span>
  );
}

function TextSet({ value, onSend }: { value: string; onSend: Send }) {
  const [text, setText] = useState(value);
  return <input className="field w-[140px] py-1" value={text} onChange={(e) => setText(e.target.value)} onBlur={() => text !== value && onSend(text)} />;
}
