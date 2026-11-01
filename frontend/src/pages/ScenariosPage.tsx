import { AlertTriangle, Copy, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Labeled } from "../components/Field";
import { ScenarioEditor } from "../components/ScenarioEditor";
import { ScenarioTest } from "../components/ScenarioTest";
import { ApiError } from "../lib/api";
import { scenApi, type CatInstance, type CheckResult, type Conflict, type Scenario, type ScenarioSummary } from "../lib/scen";
import { slug } from "../lib/util";

const TYPE_LABEL: Record<string, string> = { event: "событие", value: "показание", schedule: "время", manual: "кнопка" };

export function ScenariosPage({ notify }: { notify: (t: string) => void }) {
  const [items, setItems] = useState<ScenarioSummary[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [cat, setCat] = useState<CatInstance[]>([]);
  const [doc, setDoc] = useState<Scenario | null>(null);
  const [saved, setSaved] = useState("");
  const [check, setCheck] = useState<CheckResult | null>(null);
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(async () => {
    const r = await scenApi.list();
    setItems(r.items); setConflicts(r.conflicts);
    return r.items;
  }, []);

  const open = useCallback(async (id: string) => {
    const r = await scenApi.get(id);
    setDoc(r.scenario); setSaved(JSON.stringify(r.scenario));
    setCheck(r);
  }, []);

  useEffect(() => {
    Promise.all([scenApi.catalog(), refresh()]).then(([c, list]) => {
      setCat(c.instances);
      if (list[0]) open(list.find((x) => x.id === "leak_protect")?.id ?? list[0].id);
    }).catch(() => notify("Не удалось загрузить сценарии"));
  }, [open, refresh, notify]);

  useEffect(() => {
    if (!doc) return;
    const h = setTimeout(() => scenApi.check(doc).then(setCheck).catch(() => {}), 300);
    return () => clearTimeout(h);
  }, [doc]);

  const dirty = doc !== null && JSON.stringify(doc) !== saved;
  const errors = check?.issues.filter((i) => i.severity === "error").length ?? 0;
  const confirmLeave = () => !dirty || window.confirm("Изменения не сохранены. Уйти без сохранения?");

  const save = async () => {
    if (!doc) return;
    try {
      await scenApi.save(doc, errors > 0);
      setSaved(JSON.stringify(doc)); await refresh();
      notify(errors ? "Сохранено как черновик — в сценарии есть ошибки" : "Сценарий сохранён");
    } catch (e) { notify(e instanceof ApiError ? e.message : "Не удалось сохранить"); }
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-[300px_minmax(0,1fr)_380px]">
      {/* ------------- список */}
      <aside className="flex min-h-0 flex-col border-r border-line" aria-label="Сценарии">
        <div className="flex items-baseline justify-between p-4 pb-2">
          <h2 className="text-[17px] font-semibold">Сценарии</h2>
          <span className="text-sm text-mute">{items.filter((i) => i.enabled).length} из {items.length} включены</span>
        </div>
        {conflicts.length > 0 && (
          <div className="mx-4 mb-2 rounded-md bg-[#fbefd5] p-2.5 text-[12.5px] text-warn" role="status">
            <div className="mb-1 flex items-center gap-1.5 font-semibold"><AlertTriangle size={14} aria-hidden /> Конфликт сценариев</div>
            {conflicts.map((c, i) => <p key={i}>{c.message}</p>)}
          </div>
        )}
        <ul className="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-3 pb-3">
          {items.map((s) => {
            const active = s.id === doc?.id;
            return (
              <li key={s.id}>
                <div className={`rounded-md border p-2.5 ${active ? "border-ink bg-paper" : "border-transparent hover:border-line hover:bg-paper"}`}>
                  <div className="flex items-start gap-2">
                    <button className="min-w-0 flex-1 text-left" onClick={() => { if (!active && confirmLeave()) open(s.id); }} aria-current={active}>
                      <span className={`block font-medium leading-snug ${s.enabled ? "" : "text-mute"}`}>
                        {s.title}{!s.valid && <span className="ml-1.5 inline-block h-2 w-2 rounded-full bg-bad align-middle" title="Есть ошибки" />}
                      </span>
                      <span className="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-mute" title={s.sentence}>{s.description || s.sentence}</span>
                      <span className="mt-1 flex gap-1">
                        {s.trigger_types.map((t) => <span key={t} className="rounded bg-silver px-1.5 text-[11.5px] text-mute">{TYPE_LABEL[t] ?? t}</span>)}
                      </span>
                    </button>
                    <button role="switch" aria-checked={s.enabled} aria-label={`${s.enabled ? "Выключить" : "Включить"} «${s.title}»`}
                      onClick={async () => {
                        await scenApi.enable(s.id, !s.enabled); await refresh();
                        if (active && doc) { const d = { ...doc, enabled: !s.enabled }; setDoc(d); setSaved(JSON.stringify({ ...JSON.parse(saved), enabled: !s.enabled })); }
                      }}
                      className="relative mt-0.5 h-[20px] w-[36px] shrink-0 rounded-full transition-colors" style={{ background: s.enabled ? "var(--color-g-capability)" : "var(--color-line)" }}>
                      <span className={`absolute top-[3px] h-[14px] w-[14px] rounded-full bg-white transition-[left] ${s.enabled ? "left-[19px]" : "left-[3px]"}`} />
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
          <li>
            <button className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-mute/50 p-3 text-sm text-mute hover:border-ink hover:text-ink" onClick={() => setCreating(true)}>
              <Plus size={16} aria-hidden /> Новый сценарий
            </button>
          </li>
        </ul>
      </aside>

      {/* ------------- редактор */}
      <main className="flex min-h-0 flex-col">
        {doc && (
          <div className="flex items-center gap-2 border-b border-line bg-paper px-5 py-2">
            <span className="font-mono text-[12.5px] text-mute">{doc.id}</span>
            <span className={`text-[13px] ${errors ? "text-bad" : "text-mute"}`}>
              {errors ? `ошибок: ${errors}` : dirty ? "есть несохранённые изменения" : "сохранено"}
            </span>
            <div className="ml-auto flex gap-1">
              {items.find((i) => i.id === doc.id)?.builtin && (
                <button className="btn btn-ghost text-[13px]" onClick={async () => {
                  if (!window.confirm("Вернуть сценарий к исходному?")) return;
                  const r = await scenApi.reset(doc.id); setDoc(r.scenario); setSaved(JSON.stringify(r.scenario)); await refresh();
                }}><RotateCcw size={14} aria-hidden /> Исходный</button>
              )}
              <button className="btn btn-ghost text-[13px] hover:text-bad" onClick={async () => {
                if (!window.confirm(`Удалить сценарий «${doc.title}»?`)) return;
                await scenApi.remove(doc.id); const list = await refresh(); setDoc(null);
                if (list[0]) open(list[0].id); notify("Сценарий удалён");
              }}><Trash2 size={14} aria-hidden /> Удалить</button>
              <button className="btn btn-primary" onClick={save} disabled={!dirty}><Save size={15} aria-hidden /> Сохранить</button>
            </div>
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {doc ? <ScenarioEditor doc={doc} cat={cat} issues={check?.issues ?? []} onChange={setDoc} />
            : <p className="p-8 text-mute">Выберите сценарий слева или создайте новый.</p>}
        </div>
      </main>

      {/* ------------- как читается / Ujin */}
      <aside className="min-h-0 overflow-y-auto border-l border-line bg-paper p-4" aria-label="Проверка сценария">
        {doc && (
          <div className="space-y-7">
            <ScenarioTest doc={doc} saved={!dirty}
              onRunLive={async () => {
                try {
                  const r: any = await fetch(`/api/scenarios/${doc.id}/run`, { method: "POST" }).then((x) => x.json());
                  notify(r.status === "skipped" ? "Запуск пропущен: условия «И если» не выполнены" : "Сценарий запущен — смотрите раздел «Эмуляторы»");
                } catch { notify("Не удалось запустить"); }
              }} />
            <CheckPanel check={check} />
          </div>
        )}
      </aside>

      <NewScenarioDialog open={creating} taken={items.map((i) => i.id)} cat={cat} onClose={() => setCreating(false)}
        onCreate={async (d) => {
          await scenApi.create(d); await refresh(); setCreating(false); await open(d.id); notify("Сценарий создан");
        }} />
    </div>
  );
}

function CheckPanel({ check }: { check: CheckResult | null }) {
  const [copied, setCopied] = useState(false);
  if (!check) return <p className="text-sm text-mute">Проверяю…</p>;
  const problems = check.issues.filter((i) => i.severity !== "info");
  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-2 text-sm font-semibold">Как это читается</h3>
        {check.text ? (
          <div className="space-y-2.5 rounded-md bg-white p-3 text-[14px] leading-relaxed">
            <Part label="Когда" color="var(--color-g-property)" items={check.text.when} joiner="или" />
            {check.text.if.length > 0 && <Part label="И если" color="var(--color-g-setting)" items={check.text.if} joiner="и" />}
            <Part label="То" color="var(--color-g-capability)" items={check.text.do} ordered />
          </div>
        ) : <p className="text-sm text-bad">Исправьте ошибки — и здесь появится сценарий человеческими словами.</p>}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Проверка {problems.length ? `· ${problems.length}` : ""}</h3>
        {problems.length === 0 && !check.conflicts?.length ? <p className="text-[13px] text-mute">Ошибок и конфликтов нет.</p> : (
          <ul className="space-y-1.5 text-[13px]">
            {check.conflicts?.map((c, i) => <li key={`c${i}`} className="rounded-md bg-[#fbefd5] p-2 text-warn">{c.message}</li>)}
            {problems.map((i, k) => (
              <li key={k} className={`rounded-md bg-white p-2 ${i.severity === "error" ? "text-bad" : "text-warn"}`}>{i.message}</li>
            ))}
          </ul>
        )}
      </section>

      {check.ujin && (
        <section>
          <h3 className="mb-1 text-sm font-semibold">На платформе Ujin</h3>
          <p className="mb-2 text-[13px] text-mute">
            {check.ujin.exportable
              ? "Эту часть сценария можно завести в autoscripts резидента — платформа будет исполнять её сама."
              : "Платформа не сможет исполнить этот сценарий сама — его исполняет движок R Studio и публикует результат на стенд."}
          </p>
          {check.ujin.exportable && (
            <div className="space-y-1">
              {check.ujin.conditions.map((c) => <code key={c} className="block break-all rounded bg-white p-1.5 font-mono text-[11.5px]">{c}</code>)}
              {check.ujin.set_signals.map((c) => <code key={c} className="block break-all rounded bg-white p-1.5 font-mono text-[11.5px] text-g-capability">{c}</code>)}
              <button className="btn btn-ghost px-1 text-[13px]" onClick={() => {
                navigator.clipboard?.writeText(JSON.stringify(check.ujin!.requests, null, 2)); setCopied(true); setTimeout(() => setCopied(false), 1500);
              }}><Copy size={14} aria-hidden /> {copied ? "Скопировано" : "Копировать запросы autoscripts/edit"}</button>
            </div>
          )}
          {check.ujin.skipped.length > 0 && (
            <details className="mt-2 text-[13px]">
              <summary className="cursor-pointer text-mute">Что остаётся за R Studio · {check.ujin.skipped.length}</summary>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-mute">{check.ujin.skipped.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </details>
          )}
        </section>
      )}
    </div>
  );
}

function Part({ label, color, items, joiner, ordered }: { label: string; color: string; items: string[]; joiner?: string; ordered?: boolean }) {
  return (
    <div>
      <span className="font-semibold" style={{ color }}>{label}</span>
      {ordered ? (
        <ol className="mt-0.5 list-decimal space-y-0.5 pl-5">{items.map((x, i) => <li key={i}>{x}</li>)}</ol>
      ) : (
        <span> {items.map((x, i) => <span key={i}>{i > 0 && <span className="text-mute"> {joiner} </span>}{x}</span>)}</span>
      )}
    </div>
  );
}

function NewScenarioDialog({ open, taken, cat, onClose, onCreate }: {
  open: boolean; taken: string[]; cat: CatInstance[]; onClose: () => void; onCreate: (d: Scenario) => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    const d = ref.current; if (!d) return;
    if (open && !d.open) { setTitle(""); setErr(""); d.showModal(); }
    if (!open && d.open) d.close();
  }, [open]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    let id = slug(title, 36); let n = 2; const base = id;
    while (taken.includes(id)) id = `${base}_${n++}`;
    const i = cat.find((x) => x.events.length);
    try {
      await onCreate({
        rsl: "1.0", id, title, description: "", enabled: true,
        triggers: [{ type: "event", instance: i?.id, event: i?.events[0]?.name }],
        conditions: [], match: "all",
        actions: [{ type: "notify", text: "", severity: "info", to: "resident" }], cooldown: 0,
      });
    } catch (x) { setErr(x instanceof ApiError ? x.message : "Не получилось"); }
  };
  return (
    <dialog ref={ref} onClose={onClose} className="m-auto w-[440px] rounded-lg border border-line bg-paper p-0 text-ink backdrop:bg-ink/40">
      <form onSubmit={submit} className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">Новый сценарий</h2>
        <Labeled label="Название" hint="Например, «Ухожу из дома» или «Ночной режим»">
          <input className="field" autoFocus required value={title} onChange={(e) => setTitle(e.target.value)} />
        </Labeled>
        {err && <p className="text-[13px] text-bad">{err}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>Отмена</button>
          <button type="submit" className="btn btn-primary">Создать сценарий</button>
        </div>
      </form>
    </dialog>
  );
}
