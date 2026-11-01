import { Copy, Play, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { DeviceDoc, Issue, SignalSpec, SimResult } from "../lib/types";
import { fmtValue, groupColor } from "../lib/util";
import { NumInput } from "./Field";

type Tab = "check" | "ujin" | "issues";

export function Inspector({ doc, issues }: { doc: DeviceDoc; issues: Issue[] }) {
  const [tab, setTab] = useState<Tab>("check");
  const problems = issues.filter((i) => i.severity !== "info");
  return (
    <aside className="flex h-full flex-col border-l border-line bg-paper" aria-label="Проверка устройства">
      <div role="tablist" className="flex gap-1 border-b border-line px-3 pt-3">
        {([["check", "Проверка"], ["ujin", "Для Ujin"], ["issues", `Замечания${problems.length ? ` · ${problems.length}` : ""}`]] as [Tab, string][]).map(([k, t]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === k ? "border-hg text-ink" : "border-transparent text-mute hover:text-ink"}`}>
            {t}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {tab === "check" && <CheckTab doc={doc} blocked={issues.some((i) => i.severity === "error")} />}
        {tab === "ujin" && <UjinTab doc={doc} blocked={issues.some((i) => i.severity === "error")} />}
        {tab === "issues" && <IssuesTab issues={issues} />}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------- проверка
interface Step { at: number; signal: string; value: number }

function suggestSteps(doc: DeviceDoc): Step[] {
  const steps: Step[] = [];
  const env = doc.signals.filter((s) => s.group === "environment");
  env.forEach((s, i) => {
    const t = s.type ?? "number";
    const v = t === "bool" ? 1 : Math.round(Number(s.max ?? (Number(s.default) || 1) * 3));
    steps.push({ at: 5 + i * 5, signal: s.name, value: v });
  });
  const btn = doc.signals.find((s) => s.type === "button");
  if (btn) steps.push({ at: 3, signal: btn.name, value: 1 });
  if (!steps.length) {
    const cap = doc.signals.find((s) => s.group === "capability");
    if (cap) steps.push({ at: 5, signal: cap.name, value: cap.type === "bool" ? (Number(cap.default) ? 0 : 1) : Number(cap.max ?? 1) });
  }
  return steps.sort((a, b) => a.at - b.at);
}

function CheckTab({ doc, blocked }: { doc: DeviceDoc; blocked: boolean }) {
  const [seconds, setSeconds] = useState(60);
  const [steps, setSteps] = useState<Step[]>(() => suggestSteps(doc));
  const [res, setRes] = useState<SimResult | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { setSteps(suggestSteps(doc)); setRes(null); setErr(""); // новое устройство — новый план
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.id]);

  const inputs = doc.signals.filter((s) => s.group === "environment" || s.group === "capability" || s.group === "setting");
  const byName = useMemo(() => Object.fromEntries(doc.signals.map((s) => [s.name, s])), [doc.signals]);

  const run = async () => {
    setBusy(true); setErr("");
    try {
      setRes(await api.simulate(doc, seconds, steps));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Не удалось запустить");
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-mute">Прогоните физику без сети: что меняем и когда, а ниже — как ответит устройство.</p>
      <div className="space-y-1.5">
        {steps.map((s, i) => {
          const sig = byName[s.signal];
          return (
            <div key={i} className="flex items-center gap-1.5">
              <NumInput className="w-14 py-1" value={s.at} label="Секунда" onChange={(v) => setSteps(steps.map((x, k) => k === i ? { ...x, at: v ?? 0 } : x))} />
              <span className="text-[13px] text-mute">с</span>
              <select className="field min-w-0 flex-1 py-1" value={s.signal} aria-label="Сигнал"
                onChange={(e) => setSteps(steps.map((x, k) => k === i ? { ...x, signal: e.target.value } : x))}>
                {inputs.map((x) => <option key={x.name} value={x.name}>{x.title || x.name}</option>)}
              </select>
              {sig && (sig.type === "bool" || sig.type === "enum") ? (
                <select className="field w-28 py-1" value={s.value} aria-label="Значение"
                  onChange={(e) => setSteps(steps.map((x, k) => k === i ? { ...x, value: Number(e.target.value) } : x))}>
                  {Object.entries(sig.options ?? { "0": "0", "1": "1" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              ) : (
                <NumInput className="w-20 py-1" value={s.value} label="Значение" onChange={(v) => setSteps(steps.map((x, k) => k === i ? { ...x, value: v ?? 0 } : x))} />
              )}
              <button className="btn btn-ghost px-1.5 text-mute" aria-label="Убрать шаг" onClick={() => setSteps(steps.filter((_, k) => k !== i))}>
                <Trash2 size={14} aria-hidden />
              </button>
            </div>
          );
        })}
        <button className="btn btn-ghost px-1 text-[13px]" disabled={!inputs.length}
          onClick={() => setSteps([...steps, { at: (steps.at(-1)?.at ?? 0) + 5, signal: inputs[0]?.name ?? "", value: 1 }])}>
          <Plus size={14} aria-hidden /> Шаг
        </button>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-sm text-mute">Длительность</span>
        <NumInput className="w-20" value={seconds} label="Длительность" onChange={(v) => setSeconds(Math.max(1, Math.min(3600, v ?? 60)))} />
        <span className="text-sm text-mute">с</span>
        <button className="btn btn-primary ml-auto" onClick={run} disabled={busy || blocked}>
          <Play size={15} aria-hidden /> {busy ? "Считаю…" : "Проверить"}
        </button>
      </div>
      {blocked && <p className="text-[13px] text-bad">Исправьте ошибки в описании — тогда можно проверить.</p>}
      {err && <p className="text-[13px] text-bad">{err}</p>}
      {res && <SimView res={res} byName={byName} steps={steps} />}
    </div>
  );
}

function SimView({ res, byName, steps }: { res: SimResult; byName: Record<string, SignalSpec>; steps: Step[] }) {
  const order = ["property", "capability", "environment", "setting"];
  const names = Object.keys(res.series)
    .filter((n) => byName[n] && byName[n].type !== "text")
    .sort((a, b) => order.indexOf(byName[a].group) - order.indexOf(byName[b].group));
  const T = res.t.at(-1) || 1;
  return (
    <div className="space-y-4">
      <div className="space-y-2.5">
        {names.map((n) => {
          const s = byName[n];
          const vals = res.series[n].map(Number);
          const last = res.series[n].at(-1);
          return (
            <div key={n}>
              <div className="flex items-baseline justify-between gap-2 text-[13px]">
                <span className="truncate">{s.title || n}</span>
                <span className="shrink-0 font-medium tabular-nums">{fmtValue(s, last)}</span>
              </div>
              <Spark values={vals} t={res.t} T={T} color={groupColor(s.group)} marks={steps.filter((x) => x.signal === n).map((x) => x.at)}
                stepped={s.type === "bool" || s.type === "enum" || s.type === "button"} label={s.title || n} />
            </div>
          );
        })}
      </div>
      <div>
        <h4 className="mb-1 text-sm font-semibold">События</h4>
        {res.events.length === 0 ? <p className="text-[13px] text-mute">Ни одно событие не случилось.</p> : (
          <ul className="space-y-1">
            {res.events.map((e, i) => (
              <li key={i} className="flex gap-2 text-[13px]">
                <span className="w-10 shrink-0 text-right tabular-nums text-mute">{e.t}с</span>
                <span className={e.severity === "critical" ? "font-medium text-bad" : e.severity === "warning" ? "text-warn" : ""}>{e.title}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {(res.log.length > 0 || res.errors.length > 0) && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold">Журнал устройства</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white p-2 font-mono text-[12px] text-mute">
            {[...res.errors.map((e) => "ошибка: " + e), ...res.log].join("\n")}
          </pre>
        </details>
      )}
    </div>
  );
}

export function Spark({ values, t, T, color, stepped, marks, label }: {
  values: number[]; t: number[]; T: number; color: string; stepped: boolean; marks: number[]; label: string;
}) {
  const W = 300, H = 34;
  let lo = Math.min(...values), hi = Math.max(...values);
  if (lo === hi) { lo -= 1; hi += 1; }
  const x = (s: number) => (s / T) * W;
  const y = (v: number) => H - 3 - ((v - lo) / (hi - lo)) * (H - 6);
  let d = "";
  values.forEach((v, i) => {
    const px = x(t[i]), py = y(v);
    if (i === 0) d += `M${px},${py}`;
    else d += stepped ? `H${px}V${py}` : `L${px},${py}`;
  });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-[34px] w-full" preserveAspectRatio="none" role="img"
      aria-label={`${label}: от ${Math.min(...values)} до ${Math.max(...values)}`}>
      <line x1="0" x2={W} y1={H - 1} y2={H - 1} stroke="var(--color-line)" strokeWidth="1" />
      {marks.map((m, i) => <line key={i} x1={x(m)} x2={x(m)} y1="0" y2={H} stroke="var(--color-ink)" strokeDasharray="2 2" strokeWidth="1" opacity=".4" />)}
      <path d={d} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

// ---------------------------------------------------------------- Ujin
function UjinTab({ doc, blocked }: { doc: DeviceDoc; blocked: boolean }) {
  const [data, setData] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (blocked) return;
    let alive = true;
    const h = setTimeout(() => api.compile(doc).then((r) => alive && setData(r.ujin)).catch(() => alive && setData(null)), 250);
    return () => { alive = false; clearTimeout(h); };
  }, [doc, blocked]);
  if (blocked) return <p className="text-sm text-bad">Исправьте ошибки в описании — тогда соберём декларацию для Ujin.</p>;
  if (!data) return <p className="text-sm text-mute">Собираю декларацию…</p>;
  const text = JSON.stringify(data, null, 2);
  return (
    <div className="space-y-4">
      <p className="text-sm text-mute">Так устройство увидит платформа Ujin OS: модель <code className="font-mono text-ink">{data.model}</code>,
        класс публикации <code className="font-mono text-ink">{data.class}</code>. Сигналы окружения остаются в эмуляторе.</p>
      <table className="w-full text-[13px]">
        <thead><tr className="text-left text-mute"><th className="pb-1 font-medium">Сигнал Ujin</th><th className="pb-1 font-medium">Контрол</th><th className="pb-1 font-medium">Доступ</th></tr></thead>
        <tbody>
          {data.signals.map((s: any) => (
            <tr key={s.name} className="border-t border-line">
              <td className="py-1.5 pr-2">
                <div>{s.title}</div>
                <div className="font-mono text-[11.5px] text-mute">{s.full_name}</div>
              </td>
              <td className="py-1.5 font-mono text-[12px]">{s.control}</td>
              <td className="py-1.5 font-mono text-[12px]" style={{ color: groupColor(s.group) }}>{s.management}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="list-disc space-y-1 pl-4 text-[13px] text-mute">
        {data.notes.map((n: string) => <li key={n}>{n}</li>)}
      </ul>
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-sm font-semibold">Декларация JSON</span>
          <button className="btn btn-ghost px-2 text-[13px]" onClick={() => { navigator.clipboard?.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
            <Copy size={14} aria-hidden /> {copied ? "Скопировано" : "Копировать"}
          </button>
        </div>
        <pre className="max-h-72 overflow-auto rounded bg-white p-2 font-mono text-[11.5px]">{text}</pre>
      </div>
    </div>
  );
}

function IssuesTab({ issues }: { issues: Issue[] }) {
  if (!issues.length) return <p className="text-sm text-mute">Замечаний нет — описание корректно.</p>;
  const label = { error: "Ошибка", warning: "Внимание", info: "Подсказка" } as const;
  return (
    <ul className="space-y-2">
      {issues.map((i, k) => (
        <li key={k} className="rounded-md border border-line bg-white p-2 text-[13px]">
          <div className={`font-medium ${i.severity === "error" ? "text-bad" : i.severity === "warning" ? "text-warn" : "text-mute"}`}>{label[i.severity]}</div>
          <div>{i.message}</div>
          <div className="font-mono text-[11.5px] text-mute">{i.path}</div>
        </li>
      ))}
    </ul>
  );
}
