import { ChevronDown, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { DeviceDoc, Group, Issue, SignalSpec, SigType } from "../lib/types";
import { GROUPS, exactIssues, issuesAt, slug } from "../lib/util";
import { IssueText, Labeled, NumInput } from "./Field";

const TYPES: { key: SigType; title: string }[] = [
  { key: "number", title: "Число" },
  { key: "bool", title: "Да / нет" },
  { key: "enum", title: "Варианты" },
  { key: "button", title: "Кнопка" },
  { key: "text", title: "Текст" },
];

interface Props {
  doc: DeviceDoc;
  issues: Issue[];
  onChange: (signals: SignalSpec[]) => void;
}

export function SignalsSection({ doc, issues, onChange }: Props) {
  const update = (idx: number, patch: Partial<SignalSpec>) =>
    onChange(doc.signals.map((s, i) => (i === idx ? clean({ ...s, ...patch }) : s)));
  const remove = (idx: number) => onChange(doc.signals.filter((_, i) => i !== idx));
  const add = (group: Group) => {
    const taken = new Set(doc.signals.map((s) => s.name));
    let name = group === "environment" ? "env_input" : group === "setting" ? "setting" : "signal";
    let n = 1;
    while (taken.has(n === 1 ? name : `${name}_${n}`)) n++;
    name = n === 1 ? name : `${name}_${n}`;
    const base: SignalSpec = { name, title: "", group, type: group === "capability" ? "bool" : "number" };
    if (base.type === "bool") base.options = { "0": "выкл", "1": "вкл" };
    onChange([...doc.signals, base]);
  };

  return (
    <section aria-labelledby="sig-h" className="space-y-5">
      <header>
        <h3 id="sig-h" className="text-[17px] font-semibold">Сигналы</h3>
        <p className="text-sm text-mute">Всё, что устройство знает о себе и мире. Порядок групп — как их увидит житель и УК.</p>
      </header>
      {GROUPS.map((g) => {
        const rows = doc.signals.map((s, i) => [s, i] as const).filter(([s]) => (s.group ?? "property") === g.key);
        return (
          <div key={g.key} className="border-l-[3px] pl-4" style={{ borderColor: g.color }}>
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <div>
                <h4 className="font-semibold" style={{ color: g.color }}>{g.title}</h4>
                <p className="text-[13px] text-mute">{g.hint}</p>
              </div>
              <button className="btn btn-ghost shrink-0 text-[13px]" onClick={() => add(g.key)}>
                <Plus size={15} aria-hidden /> Добавить
              </button>
            </div>
            {rows.length === 0 && <p className="py-1 text-[13px] text-mute">Пока пусто.</p>}
            <div className="space-y-2">
              {rows.map(([s, i]) => (
                <SignalRow key={i} s={s} idx={i} issues={issuesAt(issues, `signals[${i}]`)}
                  onChange={(p) => update(i, p)} onRemove={() => remove(i)} />
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function clean(s: SignalSpec): SignalSpec {
  const out: SignalSpec = { ...s };
  (Object.keys(out) as (keyof SignalSpec)[]).forEach((k) => {
    const v = out[k];
    if (v === null || v === undefined || v === "" || (k === "options" && v && Object.keys(v as object).length === 0)) {
      if (k !== "title" && k !== "name") delete out[k];
    }
  });
  return out;
}

function SignalRow({ s, idx, issues, onChange, onRemove }: {
  s: SignalSpec; idx: number; issues: Issue[]; onChange: (p: Partial<SignalSpec>) => void; onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const type = s.type ?? "number";
  const p = `signals[${idx}]`;
  const nameAuto = !s.name || /^(signal|setting|env_input)(_\d+)?$/.test(s.name);
  const hasErr = issues.some((i) => i.severity === "error");

  return (
    <div className={`rounded-md border bg-white ${hasErr ? "border-bad/60" : "border-line"}`}>
      <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_120px_70px_86px_auto] items-start gap-2 p-2">
        <div>
          <input className={`field ${exactIssues(issues, `${p}.title`).length ? "invalid" : ""}`} value={s.title}
            placeholder="Название, например «Протечка»" aria-label="Название сигнала"
            onChange={(e) => onChange(nameAuto && e.target.value
              ? { title: e.target.value, name: slug(e.target.value) } : { title: e.target.value })} />
        </div>
        <div>
          <input className={`field code ${exactIssues(issues, `${p}.name`).length ? "invalid" : ""}`} value={s.name}
            aria-label="Техническое имя" title="Техническое имя для Ujin: латиница, цифры, _"
            onChange={(e) => onChange({ name: e.target.value })} />
        </div>
        <select className="field" value={type} aria-label="Тип"
          onChange={(e) => {
            const t = e.target.value as SigType;
            const patch: Partial<SignalSpec> = { type: t };
            if (t === "bool" && !s.options) patch.options = { "0": "выкл", "1": "вкл" };
            if (t === "enum" && !s.options) patch.options = { "0": "вариант 1", "1": "вариант 2" };
            if (t === "number" || t === "text" || t === "button") patch.options = undefined;
            onChange(patch);
          }}>
          {TYPES.map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}
        </select>
        <input className="field" value={s.unit ?? ""} placeholder="ед." aria-label="Единица"
          disabled={type !== "number"} onChange={(e) => onChange({ unit: e.target.value })} />
        {type === "text" ? (
          <input className="field" value={String(s.default ?? "")} aria-label="По умолчанию"
            onChange={(e) => onChange({ default: e.target.value })} />
        ) : type === "bool" || type === "enum" ? (
          <select className="field" value={String(Number(s.default ?? 0))} aria-label="По умолчанию"
            onChange={(e) => onChange({ default: Number(e.target.value) })}>
            {Object.entries(s.options ?? { "0": "0", "1": "1" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        ) : (
          <NumInput value={typeof s.default === "number" ? s.default : 0} label="По умолчанию"
            onChange={(v) => onChange({ default: v ?? 0 })} disabled={type === "button"} />
        )}
        <div className="flex">
          <button className="btn btn-ghost px-2" onClick={() => setOpen(!open)} aria-expanded={open}
            aria-label="Подробнее" title="Подробнее">
            <ChevronDown size={16} className={open ? "rotate-180" : ""} aria-hidden />
          </button>
          <button className="btn btn-ghost px-2 text-mute hover:text-bad" onClick={onRemove}
            aria-label={`Удалить сигнал ${s.title || s.name}`} title="Удалить">
            <Trash2 size={16} aria-hidden />
          </button>
        </div>
      </div>

      {open && (
        <div className="grid grid-cols-2 gap-3 border-t border-line p-3 md:grid-cols-4">
          {type === "number" && (
            <>
              <Labeled label="Минимум"><NumInput value={s.min} onChange={(v) => onChange({ min: v })} /></Labeled>
              <Labeled label="Максимум"><NumInput value={s.max} onChange={(v) => onChange({ max: v })} /></Labeled>
              <Labeled label="Знаков после запятой">
                <NumInput value={s.precision ?? 2} onChange={(v) => onChange({ precision: v ?? 2 })} />
              </Labeled>
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <input type="checkbox" checked={!!s.monotonic} onChange={(e) => onChange({ monotonic: e.target.checked || undefined })} />
                Только растёт (счётчик)
              </label>
            </>
          )}
          {(type === "bool" || type === "enum") && (
            <div className="col-span-2 md:col-span-4">
              <span className="mb-1 block text-[12.5px] font-medium text-mute">Подписи значений</span>
              <OptionsEditor options={s.options ?? {}} fixed={type === "bool"} onChange={(o) => onChange({ options: o })} />
            </div>
          )}
          <div className="col-span-2 md:col-span-3">
            <Labeled label="Пояснение для людей">
              <input className="field" value={s.description ?? ""} onChange={(e) => onChange({ description: e.target.value })} />
            </Labeled>
          </div>
          <Labeled label="Доступ Ujin">
            <select className="field" value={s.access ?? ""} onChange={(e) => onChange({ access: (e.target.value || undefined) as SignalSpec["access"] })}>
              <option value="">по группе</option>
              <option value="r">r — только чтение</option>
              <option value="rw">rw — чтение и запись</option>
              <option value="w">w — только запись</option>
            </select>
          </Labeled>
        </div>
      )}
      <div className="px-3 pb-2 empty:hidden"><IssueText issues={issues.filter((i) => i.severity !== "info")} /></div>
    </div>
  );
}

function OptionsEditor({ options, fixed, onChange }: { options: Record<string, string>; fixed: boolean; onChange: (o: Record<string, string>) => void }) {
  const entries = Object.entries(options);
  return (
    <div className="space-y-1.5">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center gap-2">
          <span className="w-8 text-right font-mono text-sm text-mute">{k}</span>
          <input className="field" value={v} aria-label={`Подпись для ${k}`}
            onChange={(e) => onChange({ ...options, [k]: e.target.value })} />
          {!fixed && entries.length > 2 && (
            <button className="btn btn-ghost px-2" aria-label="Удалить вариант"
              onClick={() => { const o = { ...options }; delete o[k]; onChange(o); }}>
              <Trash2 size={14} aria-hidden />
            </button>
          )}
        </div>
      ))}
      {!fixed && (
        <button className="btn btn-ghost text-[13px]" onClick={() => {
          const next = entries.length ? Math.max(...entries.map(([k]) => Number(k))) + 1 : 0;
          onChange({ ...options, [String(next)]: "" });
        }}><Plus size={14} aria-hidden /> Вариант</button>
      )}
    </div>
  );
}
