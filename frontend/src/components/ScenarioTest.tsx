import { FlaskConical, Play } from "lucide-react";
import { useEffect, useState } from "react";
import type { Note, Run } from "../lib/emu";
import type { Scenario } from "../lib/scen";
import type { SignalSpec } from "../lib/types";
import { fmtValue, groupColor } from "../lib/util";
import { Spark } from "./Inspector";
import { NoteCard, RunTrace } from "./RunTrace";

interface TestResult {
  ok: boolean;
  verdict: { status: "ok" | "partial" | "failed" | "skipped" | "silent" | "error"; message: string };
  plan: { at: number; instance?: string; signal?: string; value?: number; why: string; manual?: boolean }[];
  applied: { t: number; instance?: string; signal?: string; value?: number; why: string; ok: boolean; error?: string; manual?: boolean }[];
  notes: string[];
  seconds: number;
  t: number[];
  series: Record<string, (number | string)[]>;
  meta: Record<string, { instance: string; signal: SignalSpec }>;
  runs: Run[];
  notifications: Note[];
}

const sec = (t: number) => `${Math.round(t)} с`;
const VERDICT = {
  ok: { bg: "bg-[#e3f0e1]", fg: "text-g-environment", title: "Работает" },
  partial: { bg: "bg-[#fbefd5]", fg: "text-warn", title: "Почти" },
  failed: { bg: "bg-[#fbe4e2]", fg: "text-bad", title: "Ошибка в действиях" },
  skipped: { bg: "bg-[#fbefd5]", fg: "text-warn", title: "Условия не выполнились" },
  silent: { bg: "bg-[#fbe4e2]", fg: "text-bad", title: "Не запустился" },
  error: { bg: "bg-[#fbe4e2]", fg: "text-bad", title: "Сценарий с ошибками" },
} as const;

/** «Проверить на эмуляторе»: копия квартиры, авто-план, мгновенный прогон, вердикт и трасса. */
export function ScenarioTest({ doc, saved, onRunLive }: { doc: Scenario; saved: boolean; onRunLive: () => void }) {
  const [res, setRes] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [withOthers, setWithOthers] = useState(false);
  useEffect(() => { setRes(null); }, [doc.id]);

  const run = async () => {
    setBusy(true);
    try {
      const r = await fetch("/api/scenarios/test", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: doc, with_others: withOthers }) });
      setRes(await r.json());
    } finally { setBusy(false); }
  };

  const v = res ? VERDICT[res.verdict.status] : null;
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold">Проверка на эмуляторе</h3>
      <p className="text-[13px] text-mute">Копия квартиры, время ускорено: R Studio сама вызовет причину, подготовит условия и покажет, что сделал сценарий. Живые эмуляторы не трогаются.</p>
      <label className="flex items-center gap-1.5 text-[13px] text-mute">
        <input type="checkbox" checked={withOthers} onChange={(e) => setWithOthers(e.target.checked)} /> вместе с остальными включёнными сценариями
      </label>
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-primary" onClick={run} disabled={busy}><FlaskConical size={15} aria-hidden /> {busy ? "Проверяю…" : "Проверить сценарий"}</button>
        <button className="btn" onClick={onRunLive} disabled={!saved} title={saved ? "" : "Сначала сохраните сценарий"}>
          <Play size={15} aria-hidden /> Запустить в квартире
        </button>
      </div>

      {res && v && (
        <div className="space-y-3">
          <div className={`rounded-md p-2.5 ${v.bg}`} role="status">
            <p className={`font-semibold ${v.fg}`}>{v.title}</p>
            <p className="text-[13px]">{res.verdict.message}</p>
            {res.notes?.map((n, i) => <p key={i} className="mt-1 text-[12.5px] text-mute">{n}</p>)}
          </div>
          {res.ok && (
            <>
              <div>
                <h4 className="mb-1 text-[13px] font-semibold">Что сделала проверка</h4>
                <ul className="space-y-0.5 text-[12.5px]">
                  {res.applied.map((p, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="w-9 shrink-0 font-mono text-mute">{sec(p.t)}</span>
                      <span>{p.manual ? "нажала кнопку сценария" : `${res.meta[`${p.instance}.${p.signal}`]?.instance ?? p.instance}: ${res.meta[`${p.instance}.${p.signal}`]?.signal.title ?? p.signal} = ${fmtValue(res.meta[`${p.instance}.${p.signal}`]?.signal, p.value)}`}
                        <span className="text-mute"> — {p.why}</span>{!p.ok && <span className="text-bad"> ({p.error})</span>}</span>
                    </li>
                  ))}
                  {res.applied.length === 0 && <li className="text-mute">ничего — план пуст</li>}
                </ul>
              </div>
              {res.runs.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-[13px] font-semibold">Трасса</h4>
                  {res.runs.map((r) => <RunTrace key={r.id} run={r} clock={sec} />)}
                </div>
              )}
              {Object.keys(res.series).length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-[13px] font-semibold">Как менялись устройства · {res.seconds} с</h4>
                  {Object.entries(res.series).map(([k, vals]) => {
                    const m = res.meta[k];
                    return (
                      <div key={k}>
                        <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
                          <span className="truncate">{m.instance}: {m.signal.title}</span>
                          <span className="shrink-0 font-medium">{fmtValue(m.signal, vals[vals.length - 1])}</span>
                        </div>
                        <Spark values={vals.map(Number)} t={res.t} T={res.t[res.t.length - 1] || 1} color={groupColor(m.signal.group)}
                          marks={res.applied.filter((p) => `${p.instance}.${p.signal}` === k).map((p) => p.t)}
                          stepped={m.signal.type !== "number"} label={`${m.instance}: ${m.signal.title}`} />
                      </div>
                    );
                  })}
                </div>
              )}
              {res.notifications.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-[13px] font-semibold">Уведомления</h4>
                  {res.notifications.map((n, i) => <NoteCard key={i} n={n} clock={sec} />)}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
