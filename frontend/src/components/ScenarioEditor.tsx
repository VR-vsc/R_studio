import { ArrowDown, ArrowUp, Bell, Clock, Hand, Plus, Timer, Trash2, Zap, Activity } from "lucide-react";
import type { Issue, SignalSpec } from "../lib/types";
import { OPS, type Action, type CatInstance, type Condition, type Scenario, type Trigger } from "../lib/scen";
import { exactIssues, issuesAt } from "../lib/util";
import { IssueText, NumInput } from "./Field";

interface Props {
  doc: Scenario;
  cat: CatInstance[];
  issues: Issue[];
  onChange: (d: Scenario) => void;
}

const byRoom = (cat: CatInstance[]) => {
  const m = new Map<string, CatInstance[]>();
  cat.forEach((i) => m.set(i.room, [...(m.get(i.room) ?? []), i]));
  return [...m.entries()];
};

export function ScenarioEditor({ doc, cat, issues, onChange }: Props) {
  const set = (p: Partial<Scenario>) => onChange({ ...doc, ...p });
  const conds = doc.conditions ?? [];
  const firstWithEvents = cat.find((i) => i.events.length);

  return (
    <div className="mx-auto max-w-[860px] space-y-9 px-8 py-6">
      <section aria-label="Общее" className="space-y-3">
        <input className="w-full bg-transparent text-[28px] font-semibold leading-tight tracking-tight outline-none placeholder:text-mute/60"
          value={doc.title} placeholder="Название сценария" aria-label="Название сценария" onChange={(e) => set({ title: e.target.value })} />
        <IssueText issues={exactIssues(issues, "title")} />
        <textarea className="field min-h-[52px] resize-y" value={doc.description ?? ""} aria-label="Зачем этот сценарий"
          placeholder="Зачем этот сценарий — одной фразой для жителя и УК" onChange={(e) => set({ description: e.target.value })} />
      </section>

      {/* ---------------- КОГДА */}
      <Block step="Когда" hint="Что запускает сценарий. Если причин несколько — хватит любой." color="var(--color-g-property)">
        {doc.triggers.map((t, i) => (
          <TriggerRow key={i} t={t} cat={cat} issues={issuesAt(issues, `triggers[${i}]`)} first={i === 0}
            onChange={(nt) => set({ triggers: doc.triggers.map((x, k) => (k === i ? nt : x)) })}
            onRemove={doc.triggers.length > 1 ? () => set({ triggers: doc.triggers.filter((_, k) => k !== i) }) : undefined} />
        ))}
        <AddBtn onClick={() => set({ triggers: [...doc.triggers, { type: "event", instance: firstWithEvents?.id, event: firstWithEvents?.events[0]?.name }] })}>
          или ещё причина
        </AddBtn>
        <IssueText issues={exactIssues(issues, "triggers")} />
      </Block>

      {/* ---------------- И ЕСЛИ */}
      <Block step="И если" hint="Необязательно. Проверяется в момент запуска — например, «вентиляция не в авто»." color="var(--color-g-setting)">
        {conds.length > 1 && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-mute">Нужно, чтобы выполнялись</span>
            <select className="field w-auto py-1" value={doc.match ?? "all"} onChange={(e) => set({ match: e.target.value as "all" | "any" })} aria-label="Как сочетать условия">
              <option value="all">все условия</option>
              <option value="any">хотя бы одно</option>
            </select>
          </div>
        )}
        {conds.map((c, i) => (
          <ConditionRow key={i} c={c} cat={cat} issues={issuesAt(issues, `conditions[${i}]`)}
            onChange={(nc) => set({ conditions: conds.map((x, k) => (k === i ? nc : x)) })}
            onRemove={() => set({ conditions: conds.filter((_, k) => k !== i) })} />
        ))}
        <AddBtn onClick={() => {
          const i = cat[0]; const s = i?.signals.find((x) => x.group !== "environment");
          set({ conditions: [...conds, { instance: i?.id ?? "", signal: s?.name ?? "", op: "==", value: defaultValue(s) }] });
        }}>условие</AddBtn>
      </Block>

      {/* ---------------- ТО */}
      <Block step="То" hint="Действия по порядку. «Через N с» откладывает одно действие, «Пауза» задерживает все следующие." color="var(--color-g-capability)">
        <ol className="space-y-2">
          {doc.actions.map((a, i) => (
            <ActionRow key={i} a={a} idx={i} total={doc.actions.length} cat={cat} issues={issuesAt(issues, `actions[${i}]`)}
              onChange={(na) => set({ actions: doc.actions.map((x, k) => (k === i ? na : x)) })}
              onMove={(d) => {
                const arr = [...doc.actions]; const j = i + d;
                [arr[i], arr[j]] = [arr[j], arr[i]]; set({ actions: arr });
              }}
              onRemove={doc.actions.length > 1 ? () => set({ actions: doc.actions.filter((_, k) => k !== i) }) : undefined} />
          ))}
        </ol>
        <div className="flex flex-wrap gap-1">
          <AddBtn onClick={() => {
            const i = cat.find((x) => x.signals.some(isCommandable)); const s = i?.signals.find(isCommandable);
            set({ actions: [...doc.actions, { type: "command", instance: i?.id, signal: s?.name, value: defaultValue(s) }] });
          }}><Zap size={14} aria-hidden /> команда устройству</AddBtn>
          <AddBtn onClick={() => set({ actions: [...doc.actions, { type: "notify", text: "", severity: "info", to: "resident" }] })}>
            <Bell size={14} aria-hidden /> уведомление</AddBtn>
          <AddBtn onClick={() => set({ actions: [...doc.actions, { type: "wait", seconds: 10 }] })}>
            <Timer size={14} aria-hidden /> пауза</AddBtn>
        </div>
        <IssueText issues={exactIssues(issues, "actions")} />
      </Block>

      <section className="flex flex-wrap items-center gap-2 border-t border-line pt-5 text-sm">
        <span className="text-mute">Не запускать повторно чаще, чем раз в</span>
        <NumInput className="w-20" value={doc.cooldown ?? 0} label="Пауза между запусками" onChange={(v) => set({ cooldown: v ?? 0 })} />
        <span className="text-mute">с (0 — каждый раз)</span>
      </section>
    </div>
  );
}

function Block({ step, hint, color, children }: { step: string; hint: string; color: string; children: React.ReactNode }) {
  return (
    <section aria-label={step} className="border-l-[3px] pl-5" style={{ borderColor: color }}>
      <h3 className="text-[22px] font-semibold leading-none" style={{ color }}>{step}</h3>
      <p className="mb-3 mt-1.5 text-[13px] text-mute">{hint}</p>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function AddBtn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return <button className="btn btn-ghost px-2 text-[13px]" onClick={onClick}><Plus size={14} aria-hidden /> {children}</button>;
}

const isCommandable = (s: SignalSpec) => s.group === "capability" || s.group === "setting";

function defaultValue(s?: SignalSpec): number | string {
  if (!s) return 0;
  if (s.type === "bool" || s.type === "button") return 1;
  if (s.type === "enum") return Number(Object.keys(s.options ?? { 0: "" })[0]);
  if (s.type === "text") return "";
  return typeof s.default === "number" ? s.default : 0;
}

// ---------------------------------------------------------------- выбор устройства/сигнала/значения
function InstanceSelect({ value, cat, onChange, filter, label = "Устройство", invalid }: {
  value?: string; cat: CatInstance[]; onChange: (id: string) => void; filter?: (i: CatInstance) => boolean; label?: string; invalid?: boolean;
}) {
  const list = filter ? cat.filter(filter) : cat;
  return (
    <select className={`field w-auto max-w-[240px] ${invalid ? "invalid" : ""}`} value={value ?? ""} aria-label={label} onChange={(e) => onChange(e.target.value)}>
      {!list.some((i) => i.id === value) && <option value={value ?? ""}>{value ? `нет: ${value}` : "выберите…"}</option>}
      {byRoom(list).map(([room, items]) => (
        <optgroup key={room} label={room}>
          {items.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

function SignalSelect({ inst, value, onChange, pick, invalid }: {
  inst?: CatInstance; value?: string; onChange: (s: SignalSpec) => void; pick: (s: SignalSpec) => boolean; invalid?: boolean;
}) {
  const list = (inst?.signals ?? []).filter(pick);
  return (
    <select className={`field w-auto max-w-[220px] ${invalid ? "invalid" : ""}`} value={value ?? ""} aria-label="Сигнал"
      onChange={(e) => { const s = list.find((x) => x.name === e.target.value); if (s) onChange(s); }}>
      {!list.some((s) => s.name === value) && <option value={value ?? ""}>{value ? `нет: ${value}` : "выберите…"}</option>}
      {list.map((s) => <option key={s.name} value={s.name}>{s.title}</option>)}
    </select>
  );
}

function ValueInput({ s, value, onChange, invalid }: { s?: SignalSpec; value: unknown; onChange: (v: number | string) => void; invalid?: boolean }) {
  if (s && (s.type === "bool" || s.type === "enum") && s.options) {
    return (
      <select className={`field w-auto ${invalid ? "invalid" : ""}`} value={String(value ?? "")} aria-label="Значение" onChange={(e) => onChange(Number(e.target.value))}>
        {Object.entries(s.options).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
    );
  }
  if (s?.type === "text") return <input className="field w-40" value={String(value ?? "")} aria-label="Значение" onChange={(e) => onChange(e.target.value)} />;
  return (
    <span className="flex items-center gap-1">
      <NumInput className={`w-24 ${invalid ? "invalid" : ""}`} value={typeof value === "number" ? value : Number(value) || 0} label="Значение" onChange={(v) => onChange(v ?? 0)} />
      {s?.unit && <span className="text-sm text-mute">{s.unit}</span>}
    </span>
  );
}

// ---------------------------------------------------------------- строки
const TRIG_TYPES = [
  { key: "event", title: "событие устройства", icon: Zap },
  { key: "value", title: "показание меняется", icon: Activity },
  { key: "schedule", title: "время", icon: Clock },
  { key: "manual", title: "кнопка в приложении", icon: Hand },
] as const;

function TriggerRow({ t, cat, issues, first, onChange, onRemove }: {
  t: Trigger; cat: CatInstance[]; issues: Issue[]; first: boolean; onChange: (t: Trigger) => void; onRemove?: () => void;
}) {
  const inst = cat.find((i) => i.id === t.instance);
  const sig = inst?.signals.find((s) => s.name === t.signal);
  const bad = (k: string) => issues.some((i) => i.path.endsWith(`.${k}`) && i.severity === "error");
  const switchType = (type: Trigger["type"]) => {
    if (type === "event") { const i = cat.find((x) => x.events.length); onChange({ type, instance: i?.id, event: i?.events[0]?.name }); }
    else if (type === "value") { const i = cat[0]; const s = i?.signals.find((x) => x.group !== "setting"); onChange({ type, instance: i?.id, signal: s?.name, op: "==", value: defaultValue(s) }); }
    else if (type === "schedule") onChange({ type, at: "07:00" });
    else onChange({ type });
  };
  return (
    <div className="rounded-md border border-line bg-white p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        {!first && <span className="text-sm text-mute">или</span>}
        <select className="field w-auto" value={t.type} aria-label="Что запускает" onChange={(e) => switchType(e.target.value as Trigger["type"])}>
          {TRIG_TYPES.map((x) => <option key={x.key} value={x.key}>{x.title}</option>)}
        </select>
        {t.type === "event" && (
          <>
            <InstanceSelect value={t.instance} cat={cat} filter={(i) => i.events.length > 0} invalid={bad("instance")}
              onChange={(id) => { const i = cat.find((x) => x.id === id); onChange({ ...t, instance: id, event: i?.events[0]?.name }); }} />
            <span className="text-sm text-mute">сообщает</span>
            <select className={`field w-auto ${bad("event") ? "invalid" : ""}`} value={t.event ?? ""} aria-label="Событие" onChange={(e) => onChange({ ...t, event: e.target.value })}>
              {!inst?.events.some((e) => e.name === t.event) && <option value={t.event ?? ""}>выберите…</option>}
              {inst?.events.map((e) => <option key={e.name} value={e.name}>{e.title}</option>)}
            </select>
          </>
        )}
        {t.type === "value" && (
          <>
            <InstanceSelect value={t.instance} cat={cat} invalid={bad("instance")}
              onChange={(id) => { const s = cat.find((x) => x.id === id)?.signals.find((x) => x.group !== "setting"); onChange({ ...t, instance: id, signal: s?.name, value: defaultValue(s) }); }} />
            <SignalSelect inst={inst} value={t.signal} pick={() => true} invalid={bad("signal")} onChange={(s) => onChange({ ...t, signal: s.name, value: defaultValue(s) })} />
            <select className="field w-auto" value={t.op ?? "=="} aria-label="Как меняется" onChange={(e) => onChange({ ...t, op: e.target.value as Trigger["op"] })}>
              {OPS.filter((o) => !(sig?.options) || o.key === "==" || o.key === "!=").map((o) => <option key={o.key} value={o.key}>{o.trig}</option>)}
            </select>
            <ValueInput s={sig} value={t.value} invalid={bad("value")} onChange={(v) => onChange({ ...t, value: v })} />
          </>
        )}
        {t.type === "schedule" && (
          <>
            <select className="field w-auto" value={t.every ? "every" : "at"} aria-label="Как по времени"
              onChange={(e) => onChange(e.target.value === "every" ? { type: "schedule", every: 600 } : { type: "schedule", at: "07:00" })}>
              <option value="at">каждый день в</option>
              <option value="every">каждые</option>
            </select>
            {t.every ? (
              <><NumInput className="w-24" value={Math.round(t.every / 60)} label="Минут" onChange={(v) => onChange({ ...t, every: Math.max(1, v ?? 1) * 60 })} /><span className="text-sm text-mute">мин</span></>
            ) : (
              <input type="time" className="field w-auto" value={t.at ?? "07:00"} aria-label="Время" onChange={(e) => onChange({ ...t, at: e.target.value })} />
            )}
            <span className="text-[12.5px] text-mute">по часам модели</span>
          </>
        )}
        {t.type === "manual" && <span className="text-sm text-mute">житель запускает сценарий сам — кнопкой в приложении</span>}
        {onRemove && <RemoveBtn onClick={onRemove} label="Убрать причину" />}
      </div>
      <IssueText issues={issues} />
    </div>
  );
}

function ConditionRow({ c, cat, issues, onChange, onRemove }: { c: Condition; cat: CatInstance[]; issues: Issue[]; onChange: (c: Condition) => void; onRemove: () => void }) {
  const inst = cat.find((i) => i.id === c.instance);
  const sig = inst?.signals.find((s) => s.name === c.signal);
  return (
    <div className="rounded-md border border-line bg-white p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-mute">у</span>
        <InstanceSelect value={c.instance} cat={cat}
          onChange={(id) => { const s = cat.find((x) => x.id === id)?.signals.find((x) => x.group !== "environment"); onChange({ ...c, instance: id, signal: s?.name ?? "", value: defaultValue(s) }); }} />
        <SignalSelect inst={inst} value={c.signal} pick={(s) => s.group !== "environment"} onChange={(s) => onChange({ ...c, signal: s.name, value: defaultValue(s) })} />
        <select className="field w-auto" value={c.op} aria-label="Сравнение" onChange={(e) => onChange({ ...c, op: e.target.value as Condition["op"] })}>
          {OPS.filter((o) => !(sig?.options) || o.key === "==" || o.key === "!=").map((o) => <option key={o.key} value={o.key}>{o.cond}</option>)}
        </select>
        <ValueInput s={sig} value={c.value} onChange={(v) => onChange({ ...c, value: v })} />
        <RemoveBtn onClick={onRemove} label="Убрать условие" />
      </div>
      <IssueText issues={issues} />
    </div>
  );
}

function ActionRow({ a, idx, total, cat, issues, onChange, onMove, onRemove }: {
  a: Action; idx: number; total: number; cat: CatInstance[]; issues: Issue[];
  onChange: (a: Action) => void; onMove: (d: number) => void; onRemove?: () => void;
}) {
  const inst = cat.find((i) => i.id === a.instance);
  const sig = inst?.signals.find((s) => s.name === a.signal);
  const bad = (k: string) => issues.some((i) => i.path.endsWith(`.${k}`) && i.severity === "error");
  return (
    <li className="flex gap-2 rounded-md border border-line bg-white p-2.5">
      <div className="flex w-6 shrink-0 flex-col items-center pt-1.5">
        <span className="text-sm tabular-nums text-mute">{idx + 1}</span>
        <button className="mt-1 text-mute hover:text-ink disabled:opacity-30" disabled={idx === 0} onClick={() => onMove(-1)} aria-label="Выше"><ArrowUp size={14} /></button>
        <button className="text-mute hover:text-ink disabled:opacity-30" disabled={idx === total - 1} onClick={() => onMove(1)} aria-label="Ниже"><ArrowDown size={14} /></button>
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {a.type === "command" && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Zap size={15} className="text-g-capability" aria-label="Команда" />
              <InstanceSelect value={a.instance} cat={cat} filter={(i) => i.signals.some(isCommandable)} invalid={bad("instance")}
                onChange={(id) => { const s = cat.find((x) => x.id === id)?.signals.find(isCommandable); onChange({ ...a, instance: id, signal: s?.name, value: defaultValue(s) }); }} />
              <SignalSelect inst={inst} value={a.signal} pick={isCommandable} invalid={bad("signal")} onChange={(s) => onChange({ ...a, signal: s.name, value: defaultValue(s), hold: s.type === "button" ? undefined : a.hold })} />
              {sig?.type === "button" ? <span className="text-sm text-mute">нажать</span> : (
                <><span className="text-mute">→</span><ValueInput s={sig} value={a.value} invalid={bad("value")} onChange={(v) => onChange({ ...a, value: v })} /></>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[13px] text-mute">
              <span>через</span>
              <NumInput className="w-16 py-1" value={a.delay || null} placeholder="0" label="Задержка, с" onChange={(v) => onChange({ ...a, delay: v ?? 0 })} />
              <span>с</span>
              {sig?.type !== "button" && (
                <>
                  <span>· вернуть как было через</span>
                  <NumInput className="w-16 py-1" value={a.hold ?? null} placeholder="—" label="Вернуть через, с" onChange={(v) => onChange({ ...a, hold: v || null })} />
                  <span>с</span>
                </>
              )}
            </div>
          </>
        )}
        {a.type === "notify" && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Bell size={15} className="text-warn" aria-label="Уведомление" />
              <span className="text-sm text-mute">уведомить</span>
              <select className="field w-auto" value={a.to ?? "resident"} aria-label="Кому" onChange={(e) => onChange({ ...a, to: e.target.value as Action["to"] })}>
                <option value="resident">жителя</option><option value="uk">управляющую компанию</option><option value="all">жителя и УК</option>
              </select>
              <select className="field w-auto" value={a.severity ?? "info"} aria-label="Важность" onChange={(e) => onChange({ ...a, severity: e.target.value as Action["severity"] })}>
                <option value="info">сообщение</option><option value="warning">предупреждение</option><option value="critical">тревога</option>
              </select>
            </div>
            <input className={`field ${bad("text") ? "invalid" : ""}`} value={a.text ?? ""} aria-label="Текст уведомления"
              placeholder="Что увидит человек, например «Протечка в ванной — воду перекрыли»" onChange={(e) => onChange({ ...a, text: e.target.value })} />
          </>
        )}
        {a.type === "wait" && (
          <div className="flex items-center gap-2">
            <Timer size={15} className="text-mute" aria-label="Пауза" />
            <span className="text-sm">пауза</span>
            <NumInput className="w-20" value={a.seconds ?? 0} label="Секунд" onChange={(v) => onChange({ ...a, seconds: v ?? 0 })} />
            <span className="text-sm text-mute">с, затем следующие действия</span>
          </div>
        )}
        <IssueText issues={issues} />
      </div>
      {onRemove && <div className="pt-1"><RemoveBtn onClick={onRemove} label="Убрать действие" /></div>}
    </li>
  );
}

function RemoveBtn({ onClick, label }: { onClick: () => void; label: string }) {
  return <button className="btn btn-ghost ml-auto px-1.5 text-mute hover:text-bad" onClick={onClick} aria-label={label} title={label}><Trash2 size={15} aria-hidden /></button>;
}

