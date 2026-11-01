import { MoreHorizontal, RotateCcw, Settings2, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { EmuInstance } from "../lib/emu";
import type { SignalSpec } from "../lib/types";
import { fmtValue, symbol } from "../lib/util";
import { Control } from "./Controls";

interface Props {
  inst: EmuInstance;
  changed: (sig: string) => boolean;
  onAct: (signal: string, value: number | string) => void;
  onRestart: () => void;
  onEdit: () => void;
  onRemove: () => void;
}

const SEV_ORDER = { critical: 0, warning: 1, info: 2 } as const;

/** Карточка живого устройства: показания, пульт, «мир вокруг», настройки. */
export function DeviceCard({ inst, changed, onAct, onRestart, onEdit, onRemove }: Props) {
  const sigs = inst.signals ?? [];
  const by = (g: SignalSpec["group"]) => sigs.filter((s) => s.group === g);
  const props = by("property"), caps = by("capability"), env = by("environment"), sets = by("setting");
  const v = inst.values ?? {};
  const alarms = (inst.events ?? [])
    .filter((e) => inst.active?.includes(e.name) && e.severity !== "info")
    .sort((a, b) => SEV_ORDER[a.severity as keyof typeof SEV_ORDER] - SEV_ORDER[b.severity as keyof typeof SEV_ORDER]);
  const critical = alarms.some((a) => a.severity === "critical");

  return (
    <article className={`flex flex-col rounded-lg border bg-paper ${critical ? "border-bad ring-2 ring-bad/25" : "border-line"}`}
      aria-label={inst.title}>
      <header className="flex items-start gap-3 p-3 pb-2">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-ink text-[17px] font-semibold text-white" aria-hidden>
          {symbol(inst.device_title ?? inst.title)}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-semibold leading-tight">{inst.title}</h3>
          <p className="truncate text-[12.5px] text-mute">
            {inst.device_title}
            {inst.ujin?.ext ? <> · на стенде <span className="font-mono">{inst.ujin.ext}</span></> : null}
          </p>
        </div>
        <Menu onRestart={onRestart} onEdit={onEdit} onRemove={onRemove} />
      </header>

      {alarms.length > 0 && (
        <div className={`mx-3 mb-2 rounded-md px-2.5 py-1.5 text-[13px] font-medium ${critical ? "bg-bad text-white" : "bg-[#fbefd5] text-warn"}`} role="status">
          {alarms.map((a) => a.title).join(" · ")}
        </div>
      )}

      {inst.error ? <p className="px-3 pb-3 text-[13px] text-bad">{inst.error}</p> : (
        <div className="flex flex-1 flex-col gap-3 px-3 pb-3">
          {props.length > 0 && (
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
              {props.map((s) => (
                <div key={s.name} className="min-w-0">
                  <dt className="truncate text-[12px] text-mute">{s.title}</dt>
                  <dd className={`truncate text-[17px] font-semibold tabular-nums leading-snug transition-colors duration-700 ${changed(s.name) ? "text-g-property" : ""}`}>
                    <Value s={s} v={v[s.name]} />
                  </dd>
                </div>
              ))}
            </dl>
          )}

          {caps.length > 0 && (
            <div className="space-y-2 border-t border-line pt-2.5">
              {caps.map((s) => <Control key={s.name} s={s} value={v[s.name]} tone="var(--color-g-capability)" onSend={(x) => onAct(s.name, x)} />)}
            </div>
          )}

          {env.length > 0 && (
            <div className="space-y-2 rounded-md bg-[#e9f1e7] p-2.5">
              <p className="text-[12px] font-medium text-g-environment">Мир вокруг — меняйте, чтобы проверить реакцию</p>
              {env.map((s) => <Control key={s.name} s={s} value={v[s.name]} tone="var(--color-g-environment)" onSend={(x) => onAct(s.name, x)} />)}
            </div>
          )}

          {sets.length > 0 && (
            <details className="group mt-auto">
              <summary className="cursor-pointer text-[13px] text-mute hover:text-ink">Настройки · {sets.length}</summary>
              <div className="mt-2 space-y-2">
                {sets.map((s) => <Control key={s.name} s={s} value={v[s.name]} tone="var(--color-g-setting)" onSend={(x) => onAct(s.name, x)} />)}
              </div>
            </details>
          )}
        </div>
      )}
    </article>
  );
}

function Value({ s, v }: { s: SignalSpec; v: unknown }) {
  const t = s.type ?? "number";
  if ((t === "bool" || t === "enum") && s.options) {
    const on = Number(v) > 0;
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full" style={{ background: on ? "var(--color-g-property)" : "var(--color-line)" }} aria-hidden />
        {fmtValue(s, v)}
      </span>
    );
  }
  return <>{fmtValue(s, v)}</>;
}

function Menu({ onRestart, onEdit, onRemove }: { onRestart: () => void; onEdit: () => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const item = "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-silver";
  return (
    <div ref={ref} className="relative">
      <button className="btn btn-ghost px-1.5" aria-label="Действия с устройством" aria-expanded={open} onClick={() => setOpen(!open)}>
        <MoreHorizontal size={16} aria-hidden />
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 w-48 rounded-md border border-line bg-white py-1 shadow-lg" role="menu">
          <button role="menuitem" className={item} onClick={() => { setOpen(false); onEdit(); }}><Settings2 size={14} aria-hidden /> Название и комната</button>
          <button role="menuitem" className={item} onClick={() => { setOpen(false); onRestart(); }}><RotateCcw size={14} aria-hidden /> Начать заново</button>
          <button role="menuitem" className={`${item} text-bad`} onClick={() => { setOpen(false); onRemove(); }}><Trash2 size={14} aria-hidden /> Убрать из квартиры</button>
        </div>
      )}
    </div>
  );
}
