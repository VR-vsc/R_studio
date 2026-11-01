import { useEffect, useState } from "react";
import type { DeviceDoc, Issue } from "../lib/types";
import { exactIssues, issuesAt } from "../lib/util";
import { BehaviorSection, EventsSection, VarsSection } from "./BehaviorSection";
import { IssueText, Labeled } from "./Field";
import { SignalsSection } from "./SignalsSection";

export type View = "form" | "code";

interface Props {
  doc: DeviceDoc;
  issues: Issue[];
  categories: Record<string, string>;
  view: View;
  onChange: (doc: DeviceDoc) => void;
}

export function Editor({ doc, issues, categories, view, onChange }: Props) {
  if (view === "code") return <CodeView doc={doc} issues={issues} onChange={onChange} />;
  const set = (patch: Partial<DeviceDoc>) => onChange({ ...doc, ...patch });
  return (
    <div className="mx-auto max-w-[920px] space-y-10 px-8 py-6">
      <section aria-label="Общее" className="grid grid-cols-[1fr_200px] gap-4">
        <div className="col-span-2">
          <input className="w-full bg-transparent text-[28px] font-semibold leading-tight tracking-tight outline-none placeholder:text-mute/60 focus-visible:outline-none"
            value={doc.title} placeholder="Название устройства" aria-label="Название устройства"
            onChange={(e) => set({ title: e.target.value })} />
          <IssueText issues={exactIssues(issues, "title")} />
        </div>
        <Labeled label="Описание">
          <textarea className="field min-h-[64px] resize-y" value={doc.description ?? ""}
            placeholder="Где стоит и что делает — пару предложений для жителя и УК"
            onChange={(e) => set({ description: e.target.value })} />
        </Labeled>
        <div className="space-y-3">
          <Labeled label="Категория">
            <select className="field" value={doc.category ?? "other"} onChange={(e) => set({ category: e.target.value })}>
              {Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Labeled>
          <Labeled label="Модель Ujin" hint={`по умолчанию rs_${doc.id}`}>
            <input className="field code" value={doc.model ?? ""} placeholder={`rs_${doc.id}`} onChange={(e) => set({ model: e.target.value })} />
          </Labeled>
          <IssueText issues={issuesAt(issues, "model")} />
        </div>
      </section>

      <SignalsSection doc={doc} issues={issues} onChange={(signals) => set({ signals })} />
      <VarsSection doc={doc} issues={issues} onChange={(vars) => set({ vars })} />
      <BehaviorSection doc={doc} issues={issues} onChange={(behavior) => set({ behavior })} />
      <EventsSection doc={doc} issues={issues} onChange={(events) => set({ events })} />
    </div>
  );
}

/** Режим «Код»: то же устройство как RDL-документ. Правки сразу проверяются. */
function CodeView({ doc, issues, onChange }: { doc: DeviceDoc; issues: Issue[]; onChange: (d: DeviceDoc) => void }) {
  const [text, setText] = useState(() => JSON.stringify(doc, null, 2));
  const [parseErr, setParseErr] = useState("");
  useEffect(() => {
    try {
      if (JSON.stringify(JSON.parse(text)) !== JSON.stringify(doc)) setText(JSON.stringify(doc, null, 2));
    } catch { /* пользователь посреди правки — не трогаем */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);
  return (
    <div className="flex h-full flex-col gap-2 px-8 py-6">
      <p className="text-sm text-mute">RDL — язык описания устройств R Studio. Один документ для конструктора, эмулятора, сценариев и Ujin.</p>
      <textarea spellCheck={false} aria-label="RDL-документ"
        className={`field code min-h-0 flex-1 resize-none leading-[1.5] ${parseErr ? "invalid" : ""}`}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const d = JSON.parse(e.target.value);
            setParseErr("");
            onChange(d);
          } catch (err) {
            setParseErr((err as Error).message);
          }
        }} />
      {parseErr ? <p className="text-[13px] text-bad">JSON не разобран: {parseErr}</p>
        : <IssueText issues={issues.filter((i) => i.severity === "error").slice(0, 4).map((i) => ({ ...i, message: `${i.path}: ${i.message}` }))} />}
    </div>
  );
}
