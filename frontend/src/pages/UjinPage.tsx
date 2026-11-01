import { Check, CircleHelp, FileUp, Plug, RefreshCw, Send, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Labeled } from "../components/Field";

type Mode = "off" | "dry" | "live";

interface Cfg {
  mode: Mode; base_url: string; apartment_id: string; cls: string; interval: number; poll_tasks: boolean; naming: "full" | "short" | "both";
  ust_set: boolean; ust_masked: string; employee_ust_set: boolean; employee_ust_masked: string;
}
interface Dev {
  instance: string; title: string; room: string; device_id: string; ext: string; sn: string; signals: string[];
  status?: { published: number; errors: number; last_ok: number | null; last_error: string; created: number; last_values?: Record<string, number> };
}
interface Rec {
  at: number; method: string; path: string; note: string; mode: string; ok: boolean; status: number | string | null;
  error: string | null; ms: number; query?: Record<string, unknown>; body?: unknown; response?: unknown;
}
interface Step { title: string; ok: boolean | null; detail: string; rows?: { signal: string; emulator: unknown; platform: unknown; match: boolean; as?: string }[] }
interface State {
  cfg: Cfg; ready: string | null; devices: Dev[]; journal: Rec[]; created: number;
  last_check: { at: number; steps: Step[]; ok: boolean } | null;
}
interface Exp { id: string; title: string; exportable: boolean; conditions: string[]; set_signals: string[]; skipped: string[] }

const MODES: { key: Mode; title: string; hint: string }[] = [
  { key: "off", title: "Выключено", hint: "R Studio работает только с эмуляторами" },
  { key: "dry", title: "Пробный", hint: "запросы собираются и видны в журнале, но не отправляются" },
  { key: "live", title: "На стенд", hint: "значения привязанных устройств уходят в Ujin OS" },
];

async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `Сервер ответил ${r.status}`);
  return d as T;
}

const time = (ts: number | null | undefined) => ts ? new Date(ts * 1000).toLocaleTimeString("ru-RU") : "—";

export function UjinPage({ notify }: { notify: (t: string) => void }) {
  const [st, setSt] = useState<State | null>(null);
  const [form, setForm] = useState({ base_url: "", apartment_id: "", cls: "", ust: "", employee_ust: "" });
  const [busy, setBusy] = useState("");
  const [exp, setExp] = useState<Exp[]>([]);
  const [pushRes, setPushRes] = useState<Record<string, string>>({});
  const file = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const s = await api<State>("/api/ujin/state");
    setSt(s);
    return s;
  }, []);

  useEffect(() => {
    load().then((s) => setForm({ base_url: s.cfg.base_url, apartment_id: s.cfg.apartment_id, cls: s.cfg.cls, ust: "", employee_ust: "" }))
      .catch(() => notify("Не удалось загрузить настройки Ujin"));
    api<{ items: Exp[] }>("/api/ujin/scenarios").then((r) => setExp(r.items)).catch(() => {});
    const h = setInterval(() => load().catch(() => {}), 2000);
    return () => clearInterval(h);
  }, [load, notify]);

  const run = async (label: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(label);
    try { await fn(); await load(); if (ok) notify(ok); } catch (e) { notify((e as Error).message); } finally { setBusy(""); }
  };

  if (!st) return <div className="grid h-full place-items-center text-mute">Загружаю…</div>;
  const bound = st.devices.filter((d) => d.ext);

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_400px]">
      <div className="min-h-0 overflow-y-auto">
        <div className="mx-auto max-w-[900px] space-y-8 px-8 py-6">
          <header>
            <h1 className="text-[28px] font-semibold tracking-tight">Ujin OS</h1>
            <p className="mt-1 max-w-[70ch] text-[14px] text-mute">
              Устройства квартиры, привязанные к стенду, публикуют свои значения в Ujin — так их видят кабинет жителя и BMS.
              Команды платформы забираются опросом. Сценарии, которые платформа умеет исполнять сама, можно отправить в autoscripts.
            </p>
          </header>

          {/* --------- режим */}
          <section aria-label="Режим" className="space-y-2">
            <div className="flex rounded-md border border-line bg-white p-0.5" role="radiogroup" aria-label="Режим интеграции">
              {MODES.map((m) => (
                <button key={m.key} role="radio" aria-checked={st.cfg.mode === m.key}
                  onClick={() => run("mode", () => api("/api/ujin/config", "PUT", { mode: m.key }), m.key === "live" ? "Публикация на стенд включена" : undefined)}
                  className={`flex-1 rounded px-3 py-2 text-left ${st.cfg.mode === m.key ? (m.key === "live" ? "bg-g-capability text-white" : "bg-ink text-white") : "hover:bg-silver"}`}>
                  <span className="block text-[14px] font-semibold">{m.title}</span>
                  <span className={`block text-[12px] ${st.cfg.mode === m.key ? "text-white/80" : "text-mute"}`}>{m.hint}</span>
                </button>
              ))}
            </div>
            {st.ready && <p className="text-[13px] text-warn">Чтобы работать со стендом: {st.ready}.</p>}
          </section>

          {/* --------- доступ */}
          <section aria-labelledby="acc-h" className="space-y-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <h2 id="acc-h" className="text-[17px] font-semibold">Доступ к стенду</h2>
                <p className="text-[13px] text-mute">Быстрее всего — загрузить <code className="font-mono">доступы.json</code> из пакета команды: R Studio сама возьмёт адрес, токен резидента, квартиру и привяжет устройства.</p>
              </div>
              <input ref={file} type="file" accept=".json,application/json" className="hidden" onChange={async (e) => {
                const f = e.target.files?.[0]; e.target.value = "";
                if (!f) return;
                await run("import", async () => {
                  const data = JSON.parse(await f.text());
                  const r = await api<{ bound: { title: string }[]; cfg: Cfg; employee?: { ok: boolean; message?: string } | null }>("/api/ujin/import", "POST", data);
                  setForm({ base_url: r.cfg.base_url, apartment_id: r.cfg.apartment_id, cls: r.cfg.cls, ust: "", employee_ust: "" });
                  const emp = r.employee ? (r.employee.ok ? ", сотрудник вошёл" : `, вход сотрудника не удался: ${r.employee.message}`) : "";
                  notify(`Доступы загружены, привязано устройств: ${r.bound.length}${emp}`);
                });
              }} />
              <button className="btn shrink-0" onClick={() => file.current?.click()} disabled={busy === "import"}>
                <FileUp size={15} aria-hidden /> Загрузить доступы.json
              </button>
            </div>
            <form className="grid grid-cols-2 gap-3 rounded-md border border-line bg-paper p-4" onSubmit={(e) => {
              e.preventDefault();
              run("save", () => api("/api/ujin/config", "PUT", form), "Настройки сохранены").then(() => setForm((f) => ({ ...f, ust: "", employee_ust: "" })));
            }}>
              <Labeled label="Адрес API"><input className="field code" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></Labeled>
              <Labeled label="Квартира (apartment_id)"><input className="field code" value={form.apartment_id} onChange={(e) => setForm({ ...form, apartment_id: e.target.value })} /></Labeled>
              <Labeled label="Токен резидента (ust)" hint={st.cfg.ust_set ? `сохранён: ${st.cfg.ust_masked} — оставьте поле пустым, чтобы не менять` : "не задан"}>
                <input className="field code" type="password" autoComplete="off" value={form.ust} placeholder="ust-…" onChange={(e) => setForm({ ...form, ust: e.target.value })} />
              </Labeled>
              <Labeled label="Класс модели (поле c)"><input className="field code" value={form.cls} onChange={(e) => setForm({ ...form, cls: e.target.value })} /></Labeled>
              <Labeled label="Токен сотрудника — необязательно" hint={st.cfg.employee_ust_set ? `сохранён: ${st.cfg.employee_ust_masked}` : "нужен, чтобы читать карточки устройств (на стенде тест-ОАЭ это право сотрудника)"}>
                <input className="field code" type="password" autoComplete="off" value={form.employee_ust} onChange={(e) => setForm({ ...form, employee_ust: e.target.value })} />
              </Labeled>
              <div className="flex items-end justify-end">
                <button className="btn btn-primary" type="submit" disabled={busy === "save"}>Сохранить</button>
              </div>
              <Labeled label="Имена сигналов при отправке" hint="Проверено на стенде тест-ОАЭ: значения хранятся под короткими именами. Полные — по памятке организаторов для preprod.">
                <select className="field" value={st.cfg.naming ?? "both"}
                  onChange={(e) => run("naming", () => api("/api/ujin/config", "PUT", { naming: e.target.value }), "Сохранено — следующая отправка пойдёт с новыми именами")}>
                  <option value="short">короткие: room_temp (тест-ОАЭ)</option>
                  <option value="full">полные: integrations_devices_room_temp</option>
                  <option value="both">оба варианта</option>
                </select>
              </Labeled>
              <div className="flex items-end text-[12.5px]">
                <span className="space-x-3">
                  <a className="text-g-capability underline" href="/api/ujin/debug/difference" target="_blank" rel="noreferrer">Ответ платформы по устройствам</a>
                  <a className="text-g-capability underline" href="/api/ujin/debug/signals" target="_blank" rel="noreferrer">Какие сигналы знает стенд</a>
                </span>
              </div>
              <p className="col-span-2 text-[12px] text-mute">Токены хранятся только на этом компьютере (<code className="font-mono">backend/data/ujin.json</code>), в интерфейс и журнал попадают замаскированными.</p>
            </form>
          </section>

          {/* --------- проверка связи */}
          <section aria-labelledby="chk-h" className="space-y-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <h2 id="chk-h" className="text-[17px] font-semibold">Проверка связи</h2>
                <p className="text-[13px] text-mute">Только чтение: доступен ли стенд, принят ли токен, что платформа знает о ваших устройствах — и совпадают ли значения с эмулятором.</p>
              </div>
              <button className="btn btn-primary shrink-0" disabled={busy === "check"} onClick={() => run("check", () => api("/api/ujin/check", "POST"))}>
                <Plug size={15} aria-hidden /> {busy === "check" ? "Проверяю…" : "Проверить связь"}
              </button>
            </div>
            {st.last_check && (
              <div className="space-y-1.5 rounded-md border border-line bg-white p-3">
                <p className="text-[12px] text-mute">Проверено в {time(st.last_check.at)}</p>
                {st.last_check.steps.map((s, i) => (
                  <div key={i}>
                    <div className="flex gap-2 text-[14px]">
                      {s.ok === true ? <Check size={17} className="mt-0.5 shrink-0 text-g-environment" aria-label="да" />
                        : s.ok === false ? <X size={17} className="mt-0.5 shrink-0 text-bad" aria-label="нет" />
                          : <CircleHelp size={17} className="mt-0.5 shrink-0 text-warn" aria-label="не удалось проверить" />}
                      <span><span className="font-medium">{s.title}</span> <span className="text-mute">— {s.detail}</span></span>
                    </div>
                    {s.rows && (
                      <table className="ml-6 mt-1 text-[12.5px]">
                        <thead><tr className="text-left text-mute"><th className="pr-4 font-medium">Сигнал</th><th className="pr-4 font-medium">Эмулятор</th><th className="pr-4 font-medium">Платформа</th><th className="font-medium">Имя на платформе</th></tr></thead>
                        <tbody>{s.rows.map((r) => (
                          <tr key={r.signal}><td className="pr-4 font-mono">{r.signal}</td><td className="pr-4 tabular-nums">{String(r.emulator)}</td>
                            <td className={`pr-4 tabular-nums ${r.match ? "text-g-environment" : "text-bad"}`}>{r.platform === null || r.platform === undefined ? "нет" : String(r.platform)}</td>
                            <td className="text-mute">{r.as || "—"}</td></tr>
                        ))}</tbody>
                      </table>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* --------- устройства */}
          <section aria-labelledby="dev-h" className="space-y-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <h2 id="dev-h" className="text-[17px] font-semibold">Устройства на стенде · {bound.length}</h2>
                <p className="text-[13px] text-mute">Привязка — в «Эмуляторах» (меню карточки → «Название и комната»). Новые сигналы создаются один раз: сначала коротким именем, потом приходят значения.</p>
              </div>
              <div className="flex shrink-0 gap-1">
                <button className="btn btn-ghost text-[13px]" title="При следующей отправке снова создать словари сигналов"
                  onClick={() => run("reset", () => api("/api/ujin/reset-created", "POST"), "Сигналы будут созданы заново")}><RefreshCw size={14} aria-hidden /> Создать сигналы заново</button>
                <button className="btn" disabled={st.cfg.mode === "off" || busy === "publish"}
                  onClick={() => run("publish", () => api("/api/ujin/publish", "POST"), st.cfg.mode === "dry" ? "Запросы собраны — смотрите журнал" : "Отправлено — смотрите журнал")}>
                  <Upload size={15} aria-hidden /> Отправить всё сейчас
                </button>
              </div>
            </div>
            <table className="w-full text-[13px]">
              <thead><tr className="border-b border-line text-left text-mute">
                <th className="py-1.5 font-medium">Устройство</th><th className="font-medium">ext_guid · serialnumber</th><th className="font-medium">Сигналов</th><th className="font-medium">Отправлено</th>
              </tr></thead>
              <tbody>
                {st.devices.map((d) => (
                  <tr key={d.instance} className="border-b border-line align-top">
                    <td className="py-2 pr-3"><div className="font-medium">{d.title}</div><div className="text-[12px] text-mute">{d.room}</div></td>
                    <td className="py-2 pr-3 font-mono text-[12px]">{d.ext ? <>{d.ext}<br /><span className="text-mute">{d.sn || "нет sn"}</span></> : <span className="font-sans text-mute">не привязано</span>}</td>
                    <td className="py-2 pr-3 tabular-nums" title={d.signals.join("\n")}>{d.ext ? d.signals.length : "—"}</td>
                    <td className="py-2">
                      {!d.ext ? <span className="text-mute">только эмулятор</span> : !d.status ? <span className="text-mute">ещё не отправляли</span> : (
                        <>
                          <div className="tabular-nums">{d.status.published} знач. · {time(d.status.last_ok)}</div>
                          {d.status.last_error && <div className="text-[12px] text-bad">{d.status.last_error}</div>}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* --------- сценарии */}
          <section aria-labelledby="sc-h" className="space-y-3">
            <div>
              <h2 id="sc-h" className="text-[17px] font-semibold">Сценарии в autoscripts</h2>
              <p className="text-[13px] text-mute">Платформа исполняет сама только «сигнал = значение → установить сигнал» на привязанных устройствах. Остальное исполняет движок R Studio.</p>
            </div>
            <ul className="space-y-2">
              {exp.map((x) => (
                <li key={x.id} className="rounded-md border border-line bg-white p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium">{x.title}</div>
                      {x.exportable ? (
                        <div className="mt-1 space-y-0.5">
                          {[...x.conditions, ...x.set_signals].map((c) => <code key={c} className="block break-all font-mono text-[11.5px] text-mute">{c}</code>)}
                        </div>
                      ) : <p className="text-[12.5px] text-mute">Исполняет R Studio: {x.skipped[0]}</p>}
                      {pushRes[x.id] && <p className="mt-1 text-[12.5px]">{pushRes[x.id]}</p>}
                    </div>
                    {x.exportable && (
                      <button className="btn shrink-0 text-[13px]" disabled={!!st.ready || busy === x.id}
                        onClick={() => run(x.id, async () => {
                          const r = await api<{ results: { ok: boolean; message?: string; id?: number }[] }>(`/api/ujin/scenarios/${x.id}/push`, "POST");
                          setPushRes((p) => ({ ...p, [x.id]: r.results.every((y) => y.ok) ? `Отправлено на платформу (${r.results.length})` : `Платформа ответила: ${r.results.find((y) => !y.ok)?.message ?? "ошибка"}` }));
                        })}>
                        <Send size={14} aria-hidden /> В Ujin
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>

      {/* --------- журнал */}
      <aside className="flex min-h-0 flex-col border-l border-line bg-paper" aria-label="Журнал запросов">
        <div className="border-b border-line p-4 pb-3">
          <h2 className="font-semibold">Журнал запросов</h2>
          <p className="text-[12.5px] text-mute">Что R Studio отправила на стенд и что ответила платформа. Токены скрыты.</p>
        </div>
        <ol className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-3">
          {st.journal.length === 0 && <li className="p-2 text-sm text-mute">Запросов пока не было.</li>}
          {[...st.journal].reverse().map((r, i) => (
            <li key={`${r.at}-${i}`}>
              <details className="rounded-md bg-white px-2.5 py-1.5 ring-1 ring-line">
                <summary className="cursor-pointer list-none">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={`text-[13px] ${r.ok ? "" : "text-bad"}`}>{r.note || r.path}</span>
                    <span className="shrink-0 font-mono text-[11px] text-mute">{time(r.at)}</span>
                  </div>
                  <div className="flex gap-2 font-mono text-[11px] text-mute">
                    <span>{r.method} {r.path.replace("/api/", "")}</span>
                    <span className={r.ok ? "text-g-environment" : "text-bad"}>{String(r.status ?? "—")}</span>
                    {r.ms ? <span>{r.ms} мс</span> : null}
                  </div>
                  {r.error && <div className="text-[12px] text-bad">{r.error}</div>}
                </summary>
                <pre className="mt-1.5 max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-mute">
                  {JSON.stringify({ query: r.query, body: r.body, response: r.response }, null, 2)}
                </pre>
              </details>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
