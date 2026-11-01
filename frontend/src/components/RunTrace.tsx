import { Bell, Check, Clock3, X } from "lucide-react";
import type { Note, Run } from "../lib/emu";

const STATUS = {
  running: { text: "выполняется", cls: "text-g-capability" },
  done: { text: "выполнен", cls: "text-g-environment" },
  failed: { text: "с ошибкой", cls: "text-bad" },
  skipped: { text: "пропущен", cls: "text-mute" },
} as const;

/** Трасса запуска: почему сработал, какие условия, что и когда сделано. */
export function RunTrace({ run, clock }: { run: Run; clock: (t: number) => string }) {
  const st = STATUS[run.status];
  const steps = [...run.steps].sort((a, b) => a.t - b.t || a.i - b.i);
  return (
    <div className="rounded-md border border-line bg-white p-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13.5px] font-semibold">{run.title}</span>
        <span className="shrink-0 font-mono text-[11.5px] text-mute">{clock(run.t)}</span>
      </div>
      <p className="text-[12.5px] text-mute">
        Почему: {run.reason} · <span className={st.cls}>{st.text}</span>{run.note ? ` — ${run.note}` : ""}
      </p>
      {run.conditions.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {run.conditions.map((c, i) => (
            <li key={i} className="flex gap-1.5 text-[12.5px]">
              {c.ok ? <Check size={14} className="mt-0.5 shrink-0 text-g-environment" aria-label="выполнено" />
                : <X size={14} className="mt-0.5 shrink-0 text-bad" aria-label="не выполнено" />}
              <span>{c.text} <span className="text-mute">(сейчас: {c.actual})</span></span>
            </li>
          ))}
        </ul>
      )}
      {steps.length > 0 && (
        <ol className="mt-1.5 space-y-0.5 border-t border-line pt-1.5">
          {steps.map((s, i) => (
            <li key={i} className="flex gap-1.5 text-[12.5px]">
              {s.status === "done" ? <Check size={14} className="mt-0.5 shrink-0 text-g-environment" aria-label="сделано" />
                : s.status === "failed" ? <X size={14} className="mt-0.5 shrink-0 text-bad" aria-label="ошибка" />
                  : <Clock3 size={14} className="mt-0.5 shrink-0 text-mute" aria-label="ждёт" />}
              <span className="w-[60px] shrink-0 font-mono text-[11.5px] leading-5 text-mute">{clock(s.t)}</span>
              <span className={s.status === "waiting" ? "text-mute" : ""}>{s.text}{s.error ? <span className="text-bad"> — {s.error}</span> : null}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const TO = { resident: "Жителю", uk: "В УК", all: "Жителю и в УК" } as Record<string, string>;

/** Уведомление как на экране телефона/BMS. */
export function NoteCard({ n, clock }: { n: Note; clock: (t: number) => string }) {
  const color = n.severity === "critical" ? "var(--color-bad)" : n.severity === "warning" ? "var(--color-warn)" : "var(--color-g-capability)";
  return (
    <div className="flex gap-2.5 rounded-lg bg-white p-2.5 shadow-sm ring-1 ring-line">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-white" style={{ background: color }} aria-hidden>
        <Bell size={15} />
      </span>
      <div className="min-w-0">
        <div className="flex items-baseline justify-between gap-2 text-[12px] text-mute">
          <span>{TO[n.to] ?? n.to} · {n.title}</span>
          <span className="font-mono">{clock(n.t)}</span>
        </div>
        <p className={`text-[13.5px] leading-snug ${n.severity === "critical" ? "font-semibold" : ""}`}>{n.text}</p>
      </div>
    </div>
  );
}
