import { useEffect, useRef, useState } from "react";
import type { DeviceDoc, DeviceSummary } from "../lib/types";
import { slug } from "../lib/util";
import { Labeled } from "./Field";

interface Props {
  open: boolean;
  items: DeviceSummary[];
  categories: Record<string, string>;
  onClose: () => void;
  onCreate: (doc: DeviceDoc | { cloneOf: string; id: string; title: string }) => Promise<void>;
}

export function NewDeviceDialog({ open, items, categories, onClose, onCreate }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [base, setBase] = useState("");
  const [category, setCategory] = useState("other");
  const [err, setErr] = useState("");

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { d.showModal(); setTitle(""); setId(""); setIdTouched(false); setBase(""); setErr(""); }
    if (!open && d.open) d.close();
  }, [open]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const finalId = id || slug(title, 40);
    if (items.some((x) => x.id === finalId)) return setErr(`Устройство «${finalId}» уже есть — поменяйте техническое имя.`);
    try {
      if (base) await onCreate({ cloneOf: base, id: finalId, title });
      else await onCreate(blank(finalId, title, category));
    } catch (x) { setErr((x as Error).message); }
  };

  return (
    <dialog ref={ref} onClose={onClose} className="m-auto w-[460px] rounded-lg border border-line bg-paper p-0 text-ink backdrop:bg-ink/40">
      <form onSubmit={submit} className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">Новое устройство</h2>
        <Labeled label="Название">
          <input className="field" autoFocus required value={title} placeholder="Например, «Кран на кухне»"
            onChange={(e) => { setTitle(e.target.value); if (!idTouched) setId(slug(e.target.value, 40)); }} />
        </Labeled>
        <Labeled label="Техническое имя" hint="Латиница, цифры и _. Без дефисов — иначе Ujin молча теряет данные.">
          <input className="field code" required value={id} pattern="[a-z][a-z0-9_]{1,40}"
            onChange={(e) => { setId(e.target.value); setIdTouched(true); }} />
        </Labeled>
        <Labeled label="Начать с">
          <select className="field" value={base} onChange={(e) => setBase(e.target.value)}>
            <option value="">пустого устройства</option>
            {items.map((d) => <option key={d.id} value={d.id}>копии: {d.title}</option>)}
          </select>
        </Labeled>
        {!base && (
          <Labeled label="Категория">
            <select className="field" value={category} onChange={(e) => setCategory(e.target.value)}>
              {Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Labeled>
        )}
        {err && <p className="text-[13px] text-bad">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn" onClick={onClose}>Отмена</button>
          <button type="submit" className="btn btn-primary">Создать устройство</button>
        </div>
      </form>
    </dialog>
  );
}

function blank(id: string, title: string, category: string): DeviceDoc {
  return {
    rdl: "1.0", id, title, category, description: "",
    signals: [
      { name: "state", title: "Состояние", group: "property", type: "bool", options: { "0": "выкл", "1": "вкл" } },
      { name: "power", title: "Питание", group: "capability", type: "bool", options: { "0": "выкл", "1": "вкл" } },
    ],
    vars: {},
    behavior: [{ title: "Состояние повторяет питание", on: "tick", do: [{ set: "state", to: "power" }] }],
    events: [{ name: "turned_on", title: "Устройство включилось", when: "state == 1", severity: "info" }],
  };
}
