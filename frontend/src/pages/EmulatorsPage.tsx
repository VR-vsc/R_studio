import { FastForward, Pause, Play, Plus, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Labeled } from "../components/Field";
import { DeviceCard } from "../components/DeviceCard";
import { api, ApiError } from "../lib/api";
import { emuApi, useEmulation, type DemoState, type EmuInstance, type EmuState } from "../lib/emu";
import { NoteCard, RunTrace } from "../components/RunTrace";
import type { DeviceSummary } from "../lib/types";
import { slug } from "../lib/util";

const SPEEDS = [1, 5, 20, 60];
const ROOM_ORDER = ["Прихожая", "Гостиная", "Кухня", "Спальня", "Ванная", "Электрощит", "Двор"];

export function clock(t: number) {
  t = ((t % 86400) + 86400) % 86400;
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.floor(t % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function EmulatorsPage({ notify }: { notify: (t: string) => void }) {
  const { state, connected, recentlyChanged } = useEmulation();
  const [editing, setEditing] = useState<EmuInstance | "new" | null>(null);

  const guard = async (p: Promise<unknown>) => {
    try { await p; } catch (e) { notify(e instanceof ApiError ? e.message : "Не получилось"); }
  };

  const rooms = useMemo(() => {
    const m = new Map<string, EmuInstance[]>();
    (state?.instances ?? []).forEach((i) => m.set(i.room, [...(m.get(i.room) ?? []), i]));
    const idx = (r: string) => (ROOM_ORDER.indexOf(r) + 1 || 99);
    return [...m.entries()].sort((a, b) => idx(a[0]) - idx(b[0]) || a[0].localeCompare(b[0]));
  }, [state?.instances]);

  const clk = (t: number) => clock(t + (state?.day_start ?? 0));

  if (!state) {
    return <div className="grid h-full place-items-center text-mute">{connected ? "Загружаю квартиру…" : "Подключаюсь к эмулятору…"}</div>;
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_370px]">
      <div className="flex min-h-0 flex-col">
        <div className="flex flex-wrap items-center gap-3 border-b border-line bg-paper px-5 py-2.5">
          <button className="btn btn-primary w-[132px] justify-center" onClick={() => guard(emuApi.clock({ running: !state.running }))}
            aria-label={state.running ? "Пауза" : "Запустить время"}>
            {state.running ? <><Pause size={15} aria-hidden /> Пауза</> : <><Play size={15} aria-hidden /> Запустить</>}
          </button>
          <div className="flex items-baseline gap-2">
            <span className="text-[12.5px] text-mute">Время модели</span>
            <span className="font-mono text-[18px] font-medium tabular-nums" aria-live="off">{clk(state.t)}</span>
          </div>
          <div className="flex rounded-md border border-line bg-white p-0.5" role="radiogroup" aria-label="Скорость времени">
            {SPEEDS.map((s) => (
              <button key={s} role="radio" aria-checked={state.speed === s} onClick={() => guard(emuApi.clock({ speed: s }))}
                className={`rounded px-2.5 py-1 text-[13px] tabular-nums ${state.speed === s ? "bg-ink text-white" : "text-mute hover:text-ink"}`}>
                ×{s}
              </button>
            ))}
          </div>
          <button className="btn btn-ghost text-[13px]" onClick={() => guard(emuApi.step(60))} title="Прокрутить минуту модели мгновенно">
            <FastForward size={15} aria-hidden /> +1 мин
          </button>
          <span className={`flex items-center gap-1.5 text-[12.5px] ${connected ? "text-mute" : "text-bad"}`}>
            <span className={`h-2 w-2 rounded-full ${connected ? "bg-g-environment" : "bg-bad"}`} aria-hidden />
            {connected ? "на связи" : "нет связи с сервером"}
          </span>
          <div className="ml-auto flex gap-1">
            <DemoMenu notify={notify} />
            <button className="btn btn-ghost text-[13px]" onClick={() => {
              if (window.confirm("Вернуть квартиру к исходным 9 устройствам и обнулить время?")) guard(emuApi.reset());
            }} title="Вернуть квартиру к исходным 9 устройствам и обнулить время"><RotateCcw size={14} aria-hidden /> Сброс</button>
            <button className="btn" onClick={() => setEditing("new")}><Plus size={15} aria-hidden /> Устройство</button>
          </div>
        </div>

        {state.demo && <DemoBanner d={state.demo} />}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div className="columns-[320px] gap-4">
          {rooms.length === 0 && (
            <div className="rounded-lg border border-dashed border-mute/40 p-10 text-center">
              <p className="mb-3">В квартире пока нет устройств.</p>
              <button className="btn btn-primary" onClick={() => setEditing("new")}><Plus size={15} aria-hidden /> Поставить устройство</button>
            </div>
          )}
          {rooms.map(([room, list]) => (
            <section key={room} aria-label={room} className="mb-6 break-inside-avoid">
              <h2 className="mb-2.5 text-[17px] font-semibold">{room} <span className="font-normal text-mute">· {list.length}</span></h2>
              <div className="space-y-3">
                {list.map((i) => (
                  <DeviceCard key={i.id} inst={i} changed={(sig) => recentlyChanged(i.id, sig)}
                    onAct={(sig, val) => guard(emuApi.act(i.id, sig, val))}
                    onRestart={() => guard(emuApi.restart(i.id))}
                    onEdit={() => setEditing(i)}
                    onRemove={() => { if (window.confirm(`Убрать «${i.title}» из квартиры?`)) guard(emuApi.remove(i.id)); }} />
                ))}
              </div>
            </section>
          ))}
          </div>
        </div>
      </div>

      <EventFeed state={state} clk={clk} notify={notify} />

      <InstanceDialog value={editing} rooms={rooms.map(([r]) => r)} taken={state.instances.map((i) => i.id)}
        onClose={() => setEditing(null)}
        onSubmit={async (cfg, isNew) => {
          if (isNew) await emuApi.add(cfg);
          else await emuApi.update(cfg.id, { title: cfg.title, room: cfg.room, ujin: cfg.ujin });
          setEditing(null);
          notify(isNew ? "Устройство поставлено в квартиру" : "Изменения сохранены");
        }} />
    </div>
  );
}

// ---------------------------------------------------------------- демо
function DemoBanner({ d }: { d: DemoState }) {
  return (
    <div className="flex items-center gap-4 border-b border-line bg-ink px-5 py-3 text-white" role="status" aria-live="polite">
      <span className="shrink-0 rounded bg-white/15 px-2 py-0.5 text-[12px] tabular-nums">
        {d.title} · {d.step}/{d.total}
      </span>
      <p className="min-w-0 flex-1 text-[17px] font-medium leading-snug">{d.caption}</p>
      {!d.done && <button className="btn shrink-0 border-white/30 bg-transparent text-[13px] text-white hover:border-white"
        onClick={() => fetch("/api/demo/stop", { method: "POST" })}>Остановить</button>}
    </div>
  );
}

function DemoMenu({ notify }: { notify: (t: string) => void }) {
  const [open, setOpen] = useState(false);
  const [stories, setStories] = useState<{ id: string; title: string; about: string }[]>([]);
  useEffect(() => { fetch("/api/demo").then((r) => r.json()).then((d) => setStories(d.stories)).catch(() => {}); }, []);
  return (
    <div className="relative">
      <button className="btn text-[13px]" aria-expanded={open} onClick={() => setOpen(!open)}><Play size={14} aria-hidden /> Демо</button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-80 rounded-md border border-line bg-white py-1 shadow-lg" role="menu">
          {stories.map((s) => (
            <button key={s.id} role="menuitem" className="block w-full px-3 py-2 text-left hover:bg-silver"
              onClick={async () => {
                setOpen(false);
                const r = await fetch(`/api/demo/${s.id}/start`, { method: "POST" });
                if (!r.ok) notify("Не удалось запустить демо");
              }}>
              <span className="block text-[14px] font-medium">{s.title}</span>
              <span className="block text-[12.5px] text-mute">{s.about}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- лента: события, сценарии, уведомления
type FeedTab = "events" | "runs" | "notes" | "log";

function EventFeed({ state, clk, notify }: { state: EmuState; clk: (t: number) => string; notify: (t: string) => void }) {
  const [tab, setTab] = useState<FeedTab>("runs");
  const [alarmsOnly, setAlarmsOnly] = useState(false);
  const [seen, setSeen] = useState(0);
  const [buttons, setButtons] = useState<{ id: string; title: string }[]>([]);
  const names = Object.fromEntries(state.instances.map((i) => [i.id, i.title]));
  const events = [...state.events].reverse().filter((e) => !alarmsOnly || e.severity !== "info");
  const runs = [...state.runs].reverse();
  const notes = [...state.notes].reverse();
  const fresh = Math.max(0, state.notes.length - seen);
  useEffect(() => { if (tab === "notes") setSeen(state.notes.length); }, [tab, state.notes.length]);
  useEffect(() => {
    fetch("/api/scenarios").then((r) => r.json()).then((d) => setButtons(
      d.items.filter((x: any) => x.enabled && x.valid && x.trigger_types.includes("manual")).map((x: any) => ({ id: x.id, title: x.title })))).catch(() => {});
  }, []);
  const tabs: [FeedTab, string][] = [["runs", "Сценарии"], ["notes", fresh ? `Уведомления · ${fresh}` : "Уведомления"], ["events", "События"], ["log", "Журнал"]];
  return (
    <aside className="flex min-h-0 flex-col border-l border-line bg-paper" aria-label="Что происходит в квартире">
      <div role="tablist" className="flex items-center gap-0.5 border-b border-line px-2 pt-3">
        {tabs.map(([k, t]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`-mb-px whitespace-nowrap border-b-2 px-1.5 py-2 text-[13px] font-medium ${tab === k ? "border-hg text-ink" : "border-transparent text-mute hover:text-ink"} ${k === "notes" && fresh ? "text-bad" : ""}`}>{t}</button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3" aria-live="polite">
        {tab === "runs" && (
          <div className="space-y-2">
            {buttons.length > 0 && (
              <div className="rounded-md bg-white p-2.5 ring-1 ring-line">
                <p className="mb-1.5 text-[12px] text-mute">Кнопки сценариев — как в приложении жителя</p>
                <div className="flex flex-wrap gap-1.5">
                  {buttons.map((b) => (
                    <button key={b.id} className="btn py-1 text-[13px]" onClick={() => emuApi.runScenario(b.id).catch(() => notify("Не удалось запустить"))}>
                      <Play size={13} aria-hidden /> {b.title}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {runs.length === 0 ? <p className="p-2 text-sm text-mute">Сценарии ещё не запускались. Налейте воду под датчик протечки или откройте окно в гостиной — и смотрите сюда.</p>
              : runs.map((r) => <RunTrace key={r.id} run={r} clock={clk} />)}
          </div>
        )}
        {tab === "notes" && (
          notes.length === 0 ? <p className="p-2 text-sm text-mute">Уведомлений пока нет. Их отправляют сценарии жителю и в УК.</p>
            : <div className="space-y-2">{notes.map((n) => <NoteCard key={`${n.id}-${n.t}`} n={n} clock={clk} />)}</div>
        )}
        {tab === "events" && (
          <>
            <label className="mb-2 flex items-center gap-1.5 text-[12.5px] text-mute">
              <input type="checkbox" checked={alarmsOnly} onChange={(e) => setAlarmsOnly(e.target.checked)} /> только важные
            </label>
            {events.length === 0 ? <p className="p-2 text-sm text-mute">Событий пока нет.</p> : (
              <ol className="space-y-1.5">
                {events.map((e) => (
                  <li key={e.id} className="rounded-md border-l-[3px] bg-white px-2.5 py-1.5"
                    style={{ borderColor: e.severity === "critical" ? "var(--color-bad)" : e.severity === "warning" ? "var(--color-warn)" : "var(--color-line)" }}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className={`text-[13.5px] ${e.severity === "critical" ? "font-semibold text-bad" : e.severity === "warning" ? "font-medium" : ""}`}>{e.title}</span>
                      <span className="shrink-0 font-mono text-[11.5px] text-mute">{clk(e.t)}</span>
                    </div>
                    <div className="text-[12px] text-mute">{e.instance_title} · {e.room}</div>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
        {tab === "log" && (
          <ol className="space-y-0.5 font-mono text-[11.5px]">
            {[...state.logs].reverse().map((l, k) => (
              <li key={k}><span className="text-mute">{clk(l.t)}</span> <span className="text-g-capability">{names[l.instance] ?? (l.instance === "engine" ? "движок" : l.instance)}</span> {l.text.replace(/^\[[^\]]+\]\s*/, "")}</li>
            ))}
          </ol>
        )}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------- добавить/настроить
interface Cfg { id: string; device_id: string; title: string; room: string; ujin: { ext?: string; sn?: string } }

function InstanceDialog({ value, rooms, taken, onClose, onSubmit }: {
  value: EmuInstance | "new" | null; rooms: string[]; taken: string[];
  onClose: () => void; onSubmit: (cfg: Cfg, isNew: boolean) => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [lib, setLib] = useState<DeviceSummary[]>([]);
  const [cfg, setCfg] = useState<Cfg>({ id: "", device_id: "", title: "", room: "", ujin: {} });
  const [err, setErr] = useState("");
  const isNew = value === "new";

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (value && !d.open) {
      setErr("");
      if (value === "new") {
        api.devices().then((l) => {
          setLib(l.filter((x) => x.valid));
          const first = l.find((x) => x.valid);
          setCfg({ id: "", device_id: first?.id ?? "", title: first?.title ?? "", room: rooms[0] ?? "Гостиная", ujin: {} });
        });
      } else {
        setCfg({ id: value.id, device_id: value.device_id, title: value.title, room: value.room, ujin: { ...value.ujin } });
      }
      d.showModal();
    }
    if (!value && d.open) d.close();
  }, [value, rooms]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    let id = cfg.id;
    if (isNew) {
      const base = slug(`${cfg.room} ${cfg.title}`, 36);
      id = base; let n = 2;
      while (taken.includes(id)) id = `${base}_${n++}`;
    }
    try { await onSubmit({ ...cfg, id }, isNew); } catch (x) { setErr(x instanceof ApiError ? x.message : "Не получилось"); }
  };

  return (
    <dialog ref={ref} onClose={onClose} className="m-auto w-[460px] rounded-lg border border-line bg-paper p-0 text-ink backdrop:bg-ink/40">
      <form onSubmit={submit} className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">{isNew ? "Поставить устройство в квартиру" : "Устройство в квартире"}</h2>
        {isNew && (
          <Labeled label="Какое устройство">
            <select className="field" value={cfg.device_id} required
              onChange={(e) => { const d = lib.find((x) => x.id === e.target.value); setCfg({ ...cfg, device_id: e.target.value, title: d?.title ?? cfg.title }); }}>
              {lib.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
            </select>
          </Labeled>
        )}
        <Labeled label="Название в квартире">
          <input className="field" required value={cfg.title} onChange={(e) => setCfg({ ...cfg, title: e.target.value })} />
        </Labeled>
        <Labeled label="Комната">
          <input className="field" required list="rooms" value={cfg.room} onChange={(e) => setCfg({ ...cfg, room: e.target.value })} />
          <datalist id="rooms">{[...new Set([...rooms, ...ROOM_ORDER])].map((r) => <option key={r} value={r} />)}</datalist>
        </Labeled>
        {!isNew && (
          <fieldset className="space-y-3 rounded-md border border-line p-3">
            <legend className="px-1 text-[12.5px] font-medium text-mute">Устройство на стенде Ujin (если есть)</legend>
            <Labeled label="ext_guid (sn в публикации)">
              <input className="field code" value={cfg.ujin.ext ?? ""} placeholder="rtut_leak_01"
                onChange={(e) => setCfg({ ...cfg, ujin: { ...cfg.ujin, ext: e.target.value } })} />
            </Labeled>
            <Labeled label="serialnumber">
              <input className="field code" value={cfg.ujin.sn ?? ""} inputMode="numeric"
                onChange={(e) => setCfg({ ...cfg, ujin: { ...cfg.ujin, sn: e.target.value } })} />
            </Labeled>
          </fieldset>
        )}
        {err && <p className="text-[13px] text-bad">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn" onClick={onClose}>Отмена</button>
          <button type="submit" className="btn btn-primary">{isNew ? "Поставить" : "Сохранить"}</button>
        </div>
      </form>
    </dialog>
  );
}
