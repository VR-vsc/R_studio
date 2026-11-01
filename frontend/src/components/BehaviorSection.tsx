import { Plus, Trash2 } from "lucide-react";
import type { ActionSpec, DeviceDoc, EventSpec, Issue, RuleSpec } from "../lib/types";
import { exactIssues, issuesAt, slug } from "../lib/util";
import { IssueText, NumInput } from "./Field";

type Trigger = "tick" | "start" | "command" | "change";

function parseOn(on: string): [Trigger, string] {
  const [k, sig] = on.split(":");
  if (k === "command") return ["command", sig ?? ""];
  if (k === "change") return ["change", sig ?? ""];
  return [k as Trigger, ""];
}

const exprText = (v: unknown) => (v === null || v === undefined ? "" : String(v));

// ---------------------------------------------------------------- память
export function VarsSection({ doc, issues, onChange }: { doc: DeviceDoc; issues: Issue[]; onChange: (v: Record<string, number | string>) => void }) {
  const vars = Object.entries(doc.vars ?? {});
  const rename = (oldK: string, newK: string) => {
    const out: Record<string, number | string> = {};
    vars.forEach(([k, v]) => { out[k === oldK ? newK : k] = v; });
    onChange(out);
  };
  return (
    <section aria-labelledby="vars-h">
      <h3 id="vars-h" className="text-[17px] font-semibold">Память устройства</h3>
      <p className="mb-2 text-sm text-mute">Внутренние счётчики и таймеры физики. Наружу не публикуются.</p>
      <div className="flex flex-wrap gap-2">
        {vars.map(([k, v]) => (
          <div key={k} className="flex items-center gap-1 rounded-md border border-line bg-white p-1">
            <input className="field code w-32 border-0" value={k} aria-label="Имя переменной" onChange={(e) => rename(k, e.target.value)} />
            <span className="text-mute">=</span>
            <NumInput className="w-20 border-0" value={typeof v === "number" ? v : Number(v) || 0} label="Начальное значение"
              onChange={(n) => onChange({ ...doc.vars, [k]: n ?? 0 })} />
            <button className="btn btn-ghost px-1.5 text-mute" aria-label={`Удалить ${k}`}
              onClick={() => { const o = { ...doc.vars }; delete o[k]; onChange(o); }}>
              <Trash2 size={14} aria-hidden />
            </button>
          </div>
        ))}
        <button className="btn btn-ghost text-[13px]" onClick={() => {
          let n = 1; while ((doc.vars ?? {})[`timer${n}`] !== undefined) n++;
          onChange({ ...(doc.vars ?? {}), [`timer${n}`]: 0 });
        }}><Plus size={14} aria-hidden /> Переменная</button>
      </div>
      <IssueText issues={issuesAt(issues, "vars")} />
    </section>
  );
}

// ---------------------------------------------------------------- правила
export function BehaviorSection({ doc, issues, onChange }: { doc: DeviceDoc; issues: Issue[]; onChange: (b: RuleSpec[]) => void }) {
  const rules = doc.behavior ?? [];
  const targets = [...doc.signals.map((s) => ({ name: s.name, title: s.title || s.name })),
    ...Object.keys(doc.vars ?? {}).map((k) => ({ name: k, title: `память: ${k}` }))];
  const commandable = doc.signals.filter((s) => (s.access ?? (s.group === "property" ? "r" : "rw")) !== "r" && s.group !== "environment");
  const set = (i: number, r: RuleSpec) => onChange(rules.map((x, k) => (k === i ? r : x)));
  const names = [...doc.signals.map((s) => s.name), ...Object.keys(doc.vars ?? {})];

  return (
    <section aria-labelledby="beh-h" className="space-y-3">
      <header className="flex items-end justify-between gap-3">
        <div>
          <h3 id="beh-h" className="text-[17px] font-semibold">Поведение</h3>
          <p className="text-sm text-mute">Физика эмулятора: правила «когда — что сделать». Выполняются по порядку сверху вниз.</p>
        </div>
        <button className="btn shrink-0" onClick={() => onChange([...rules, { on: "tick", do: [{ set: targets[0]?.name ?? "", to: "0" }] }])}>
          <Plus size={15} aria-hidden /> Правило
        </button>
      </header>

      <details className="rounded-md bg-paper px-3 py-2 text-[13px] text-mute">
        <summary className="cursor-pointer text-ink">Как писать формулы</summary>
        <p className="mt-1">Имена: <code className="font-mono text-ink">{names.join(", ")}</code>, а ещё <code className="font-mono text-ink">dt</code> — шаг в секундах,
          {" "}<code className="font-mono text-ink">t</code> — время с запуска, <code className="font-mono text-ink">value</code> — пришедшее значение команды.</p>
        <p className="mt-1">Можно: <code className="font-mono text-ink">+ - * /</code>, сравнения, <code className="font-mono text-ink">&& || !</code>,
          {" "}<code className="font-mono text-ink">1 if условие else 0</code>, функции <code className="font-mono text-ink">min max abs round clamp sign rand</code>.</p>
      </details>

      {rules.length === 0 && <p className="text-sm text-mute">Правил нет — устройство только хранит значения.</p>}

      <ol className="space-y-2">
        {rules.map((r, i) => {
          const [trig, sig] = parseOn(r.on);
          const p = `behavior[${i}]`;
          const ri = issuesAt(issues, p);
          return (
            <li key={i} className={`rounded-md border bg-white p-3 ${ri.some((x) => x.severity === "error") ? "border-bad/60" : "border-line"}`}>
              <div className="mb-2 flex items-center gap-2">
                <span className="w-6 text-right text-sm tabular-nums text-mute">{i + 1}</span>
                <input className="field border-transparent bg-transparent px-1 font-medium" value={r.title ?? ""}
                  placeholder="Опишите правило словами" aria-label="Описание правила"
                  onChange={(e) => set(i, { ...r, title: e.target.value })} />
                <button className="btn btn-ghost px-2 text-mute hover:text-bad" aria-label={`Удалить правило ${i + 1}`}
                  onClick={() => onChange(rules.filter((_, k) => k !== i))}><Trash2 size={16} aria-hidden /></button>
              </div>
              <div className="ml-8 grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2">
                <span className="text-sm text-mute">Когда</span>
                <div className="flex flex-wrap gap-2">
                  <select className="field w-auto" value={trig} aria-label="Триггер"
                    onChange={(e) => {
                      const t = e.target.value as Trigger;
                      const first = t === "command" ? commandable[0]?.name : doc.signals[0]?.name;
                      set(i, { ...r, on: t === "command" || t === "change" ? `${t}:${first ?? ""}` : t });
                    }}>
                    <option value="tick">каждую секунду</option>
                    <option value="start">при запуске</option>
                    <option value="command">пришла команда</option>
                    <option value="change">изменился сигнал</option>
                  </select>
                  {(trig === "command" || trig === "change") && (
                    <select className="field w-auto" value={sig} aria-label="Сигнал триггера"
                      onChange={(e) => set(i, { ...r, on: `${trig}:${e.target.value}` })}>
                      {(trig === "command" ? commandable : doc.signals).map((s) => (
                        <option key={s.name} value={s.name}>{s.title || s.name}</option>
                      ))}
                    </select>
                  )}
                </div>
                <span className="text-sm text-mute">и если</span>
                <div>
                  <input className={`field code ${exactIssues(issues, `${p}.when`).length ? "invalid" : ""}`} value={exprText(r.when)}
                    placeholder="всегда" aria-label="Условие"
                    onChange={(e) => set(i, { ...r, when: e.target.value || undefined })} />
                  <IssueText issues={exactIssues(issues, `${p}.when`).concat(exactIssues(issues, `${p}.on`))} />
                </div>
                {r.do.map((a, j) => (
                  <ActionRow key={j} a={a} first={j === 0} targets={targets} issues={issuesAt(issues, `${p}.do[${j}]`)}
                    onChange={(na) => set(i, { ...r, do: r.do.map((x, k) => (k === j ? na : x)) })}
                    onRemove={r.do.length > 1 ? () => set(i, { ...r, do: r.do.filter((_, k) => k !== j) }) : undefined} />
                ))}
                <span />
                <div>
                  <button className="btn btn-ghost px-1 text-[13px]" onClick={() => set(i, { ...r, do: [...r.do, { set: targets[0]?.name ?? "", to: "0" }] })}>
                    <Plus size={14} aria-hidden /> ещё действие
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function ActionRow({ a, first, targets, issues, onChange, onRemove }: {
  a: ActionSpec; first: boolean; targets: { name: string; title: string }[]; issues: Issue[];
  onChange: (a: ActionSpec) => void; onRemove?: () => void;
}) {
  const isLog = a.log !== undefined && a.log !== null;
  return (
    <>
      <span className="text-sm text-mute">{first ? "то" : "и"}</span>
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <select className="field w-auto" value={isLog ? "log" : "set"} aria-label="Тип действия"
            onChange={(e) => onChange(e.target.value === "log" ? { log: "" } : { set: targets[0]?.name ?? "", to: "0" })}>
            <option value="set">установить</option>
            <option value="log">записать в журнал</option>
          </select>
          {isLog ? (
            <input className="field min-w-0 flex-1" value={a.log ?? ""} placeholder="Текст; {имя} подставит значение"
              aria-label="Текст журнала" onChange={(e) => onChange({ log: e.target.value })} />
          ) : (
            <>
              <select className="field w-auto max-w-[220px]" value={a.set ?? ""} aria-label="Что установить"
                onChange={(e) => onChange({ ...a, set: e.target.value })}>
                {targets.map((t) => <option key={t.name} value={t.name}>{t.title}</option>)}
              </select>
              <span className="text-mute">=</span>
              <input className={`field code min-w-[160px] flex-1 ${issues.some((x) => x.path.endsWith(".to")) ? "invalid" : ""}`}
                value={exprText(a.to)} aria-label="Значение или формула" onChange={(e) => onChange({ ...a, to: e.target.value })} />
            </>
          )}
          {onRemove && (
            <button className="btn btn-ghost px-1.5 text-mute hover:text-bad" onClick={onRemove} aria-label="Удалить действие">
              <Trash2 size={14} aria-hidden />
            </button>
          )}
        </div>
        {!isLog && (
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[13px] text-mute">
            <span>через</span>
            <NumInput className="w-16 py-1" value={a.after} placeholder="0" label="Задержка, с" onChange={(v) => onChange({ ...a, after: v || undefined })} />
            <span>с; вернуть через</span>
            <NumInput className="w-16 py-1" value={a.hold} placeholder="—" label="Удержание, с" onChange={(v) => onChange({ ...a, hold: v || undefined })} />
            <span>с</span>
            {a.hold ? (
              <>
                <span>к значению</span>
                <input className="field code w-28 py-1" value={exprText(a.then)} placeholder="как было" aria-label="Значение возврата"
                  onChange={(e) => onChange({ ...a, then: e.target.value || undefined })} />
              </>
            ) : null}
          </div>
        )}
        <IssueText issues={issues} />
      </div>
    </>
  );
}

// ---------------------------------------------------------------- события
const SEV = { info: "сообщение", warning: "внимание", critical: "тревога" } as const;

export function EventsSection({ doc, issues, onChange }: { doc: DeviceDoc; issues: Issue[]; onChange: (e: EventSpec[]) => void }) {
  const events = doc.events ?? [];
  const set = (i: number, e: EventSpec) => onChange(events.map((x, k) => (k === i ? e : x)));
  return (
    <section aria-labelledby="ev-h" className="space-y-3">
      <header className="flex items-end justify-between gap-3">
        <div>
          <h3 id="ev-h" className="text-[17px] font-semibold">События</h3>
          <p className="text-sm text-mute">То, на что будут реагировать сценарии: «протечка обнаружена», «стало душно».
            Событие возникает в момент, когда условие становится истинным.</p>
        </div>
        <button className="btn shrink-0" onClick={() => onChange([...events, { name: `event_${events.length + 1}`, title: "", when: "", severity: "info" }])}>
          <Plus size={15} aria-hidden /> Событие
        </button>
      </header>
      <div className="space-y-2">
        {events.map((e, i) => {
          const p = `events[${i}]`;
          return (
            <div key={i} className="rounded-md border border-line bg-white p-2">
              <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_120px_auto] gap-2">
                <input className="field" value={e.title} placeholder="Например: «Обнаружена протечка»" aria-label="Название события"
                  onChange={(x) => set(i, { ...e, title: x.target.value, name: /^event_\d+$/.test(e.name) && x.target.value ? slug(x.target.value) : e.name })} />
                <input className="field code" value={e.name} aria-label="Техническое имя события" onChange={(x) => set(i, { ...e, name: x.target.value })} />
                <select className="field" value={e.severity} aria-label="Важность" onChange={(x) => set(i, { ...e, severity: x.target.value as EventSpec["severity"] })}>
                  {Object.entries(SEV).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <button className="btn btn-ghost px-2 text-mute hover:text-bad" aria-label="Удалить событие" onClick={() => onChange(events.filter((_, k) => k !== i))}>
                  <Trash2 size={16} aria-hidden />
                </button>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <span className="text-sm text-mute">когда</span>
                <input className={`field code ${exactIssues(issues, `${p}.when`).length ? "invalid" : ""}`} value={e.when}
                  placeholder="leak == 1" aria-label="Условие события" onChange={(x) => set(i, { ...e, when: x.target.value })} />
              </div>
              <IssueText issues={issuesAt(issues, p)} />
            </div>
          );
        })}
      </div>
    </section>
  );
}
