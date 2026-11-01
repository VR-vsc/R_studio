import { Code2, LayoutList, RotateCcw, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Editor, type View } from "../components/Editor";
import { Inspector } from "../components/Inspector";
import { Library } from "../components/Library";
import { NewDeviceDialog } from "../components/NewDeviceDialog";
import { api, ApiError } from "../lib/api";
import type { DeviceDoc, DeviceSummary, Issue } from "../lib/types";

export function ConstructorPage({ notify }: { notify: (t: string) => void }) {
  const [items, setItems] = useState<DeviceSummary[]>([]);
  const [categories, setCategories] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [doc, setDoc] = useState<DeviceDoc | null>(null);
  const [saved, setSaved] = useState("");
  const [builtin, setBuiltin] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [view, setView] = useState<View>("form");
  const [creating, setCreating] = useState(false);
  const [loadErr, setLoadErr] = useState("");

  const refresh = useCallback(async () => {
    const list = await api.devices();
    setItems(list);
    return list;
  }, []);

  const open = useCallback(async (id: string) => {
    const r = await api.device(id);
    setSelected(id);
    setDoc(r.device);
    setSaved(JSON.stringify(r.device));
    setIssues(r.issues);
    setBuiltin(r.builtin);
  }, []);

  useEffect(() => {
    Promise.all([api.meta(), refresh()])
      .then(([m, list]) => {
        setCategories(m.categories);
        const first = list.find((d) => d.id === "leak_sensor") ?? list[0];
        if (first) open(first.id);
      })
      .catch(() => setLoadErr("Сервер R Studio не отвечает. Запустите backend: uvicorn app.main:app --port 8000"));
  }, [open, refresh]);

  // живая проверка описания
  useEffect(() => {
    if (!doc) return;
    const h = setTimeout(() => api.validate(doc).then((r) => setIssues(r.issues)).catch(() => {}), 300);
    return () => clearTimeout(h);
  }, [doc]);

  const dirty = doc !== null && JSON.stringify(doc) !== saved;
  const errors = issues.filter((i) => i.severity === "error").length;

  const confirmLeave = () => !dirty || window.confirm("Изменения не сохранены. Уйти без сохранения?");

  const save = async () => {
    if (!doc) return;
    try {
      await api.save(doc, errors > 0);
      setSaved(JSON.stringify(doc));
      await refresh();
      notify(errors ? "Сохранено как черновик — в описании есть ошибки" : "Устройство сохранено");
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "Не удалось сохранить");
    }
  };

  // Ctrl+S
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  if (loadErr) {
    return <div className="grid h-full place-items-center p-8 text-center"><p className="max-w-md">{loadErr}</p></div>;
  }

  return (
    <>
      <div className="grid h-full min-h-0 grid-cols-[264px_minmax(0,1fr)_380px]">
        <Library items={items} categories={categories} selected={selected}
          onSelect={(id) => { if (id !== selected && confirmLeave()) open(id); }}
          onCreate={() => setCreating(true)} />

        <main className="flex min-h-0 flex-col">
          {doc && (
            <div className="flex items-center gap-2 border-b border-line bg-paper px-5 py-2">
              <div className="flex rounded-md border border-line bg-white p-0.5" role="group" aria-label="Вид редактора">
                <button className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-[13px] ${view === "form" ? "bg-ink text-white" : "text-mute"}`}
                  aria-pressed={view === "form"} onClick={() => setView("form")}><LayoutList size={14} aria-hidden /> Форма</button>
                <button className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-[13px] ${view === "code" ? "bg-ink text-white" : "text-mute"}`}
                  aria-pressed={view === "code"} onClick={() => setView("code")}><Code2 size={14} aria-hidden /> Код RDL</button>
              </div>
              <span className="ml-2 font-mono text-[12.5px] text-mute">{doc.id}</span>
              <span className={`text-[13px] ${errors ? "text-bad" : "text-mute"}`}>
                {errors ? `ошибок: ${errors}` : dirty ? "есть несохранённые изменения" : "сохранено"}
              </span>
              <div className="ml-auto flex gap-1">
                {builtin && (
                  <button className="btn btn-ghost text-[13px]" title="Вернуть встроенный шаблон"
                    onClick={async () => {
                      if (!window.confirm("Вернуть устройство к исходному шаблону?")) return;
                      const r = await api.reset(doc.id); setDoc(r.device); setSaved(JSON.stringify(r.device)); await refresh(); notify("Шаблон восстановлен");
                    }}><RotateCcw size={14} aria-hidden /> Шаблон</button>
                )}
                <button className="btn btn-ghost text-[13px] hover:text-bad"
                  onClick={async () => {
                    if (!window.confirm(`Удалить «${doc.title}»?`)) return;
                    await api.remove(doc.id);
                    const list = await refresh();
                    setDoc(null); setSelected(null);
                    if (list[0]) open(list[0].id);
                    notify("Устройство удалено");
                  }}><Trash2 size={14} aria-hidden /> Удалить</button>
                <button className="btn btn-primary" onClick={save} disabled={!dirty}>
                  <Save size={15} aria-hidden /> Сохранить
                </button>
              </div>
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto">
            {doc ? <Editor doc={doc} issues={issues} categories={categories} view={view} onChange={setDoc} />
              : <p className="p-8 text-mute">Выберите устройство слева или создайте новое.</p>}
          </div>
        </main>

        {doc ? <Inspector doc={doc} issues={issues} /> : <div className="border-l border-line bg-paper" />}
      </div>

      <NewDeviceDialog open={creating} items={items} categories={categories} onClose={() => setCreating(false)}
        onCreate={async (x) => {
          try {
            if ("cloneOf" in x) await api.clone(x.cloneOf, x.id, x.title);
            else await api.create(x);
          } catch (e) {
            throw new Error(e instanceof ApiError ? (e.issues[0]?.message ?? e.message) : "Не удалось создать");
          }
          await refresh();
          setCreating(false);
          await open(x.id);
          notify("Устройство создано");
        }} />

    </>
  );
}
