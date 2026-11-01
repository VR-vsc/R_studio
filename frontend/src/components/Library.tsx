import { Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { DeviceSummary } from "../lib/types";
import { GROUPS, symbol } from "../lib/util";

interface Props {
  items: DeviceSummary[];
  categories: Record<string, string>;
  selected: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
}

/** Библиотека устройств — «таблица элементов»: символ, число сигналов, состав по группам. */
export function Library({ items, categories, selected, onSelect, onCreate }: Props) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const list = useMemo(() => {
    const s = q.trim().toLowerCase();
    return items.filter((d) =>
      (!cat || d.category === cat) &&
      (!s || d.title.toLowerCase().includes(s) || d.id.includes(s)));
  }, [items, q, cat]);
  const usedCats = Array.from(new Set(items.map((d) => d.category)));

  return (
    <aside className="flex h-full flex-col border-r border-line bg-silver" aria-label="Библиотека устройств">
      <div className="space-y-2 p-4 pb-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-[17px] font-semibold">Устройства</h2>
          <span className="text-sm text-mute">{items.length}</span>
        </div>
        <label className="relative block">
          <Search size={15} className="absolute left-2.5 top-2.5 text-mute" aria-hidden />
          <input className="field pl-8" placeholder="Найти устройство" value={q}
            onChange={(e) => setQ(e.target.value)} aria-label="Поиск устройства" />
        </label>
        <div className="flex flex-wrap gap-1">
          <Chip active={!cat} onClick={() => setCat("")}>Все</Chip>
          {usedCats.map((c) => (
            <Chip key={c} active={cat === c} onClick={() => setCat(c === cat ? "" : c)}>
              {categories[c] ?? c}
            </Chip>
          ))}
        </div>
      </div>

      <div className="grid flex-1 auto-rows-min grid-cols-2 gap-2 overflow-y-auto px-4 pb-4">
        {list.map((d) => {
          const total = Object.values(d.groups).reduce((a, b) => a + (b || 0), 0);
          const active = d.id === selected;
          return (
            <button key={d.id} onClick={() => onSelect(d.id)}
              className={`group relative flex aspect-square flex-col rounded-md border p-2.5 text-left transition-colors ${
                active ? "border-ink bg-ink text-white" : "border-line bg-paper hover:border-ink"}`}
              aria-pressed={active} title={d.description}>
              <span className={`text-[11px] tabular-nums ${active ? "text-white/70" : "text-mute"}`}>{total}</span>
              <span className="mt-auto text-[30px] font-semibold leading-none tracking-tight">{symbol(d.title)}</span>
              <span className="mt-1.5 line-clamp-2 text-[12px] leading-tight">{d.title}</span>
              <span className="mt-2 flex h-1 w-full overflow-hidden rounded-full" aria-hidden>
                {GROUPS.map((g) => (d.groups[g.key] ? (
                  <span key={g.key} style={{ flex: d.groups[g.key], background: g.color }} />
                ) : null))}
              </span>
              {!d.valid && (
                <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-bad" title="Есть ошибки" />
              )}
            </button>
          );
        })}
        <button onClick={onCreate}
          className="flex aspect-square flex-col items-center justify-center gap-1 rounded-md border border-dashed border-mute/50 text-sm text-mute hover:border-ink hover:text-ink">
          <Plus size={22} aria-hidden />
          Новое устройство
        </button>
      </div>
    </aside>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} aria-pressed={active}
      className={`rounded-full border px-2.5 py-0.5 text-[12.5px] ${
        active ? "border-ink bg-ink text-white" : "border-line bg-paper text-ink hover:border-ink"}`}>
      {children}
    </button>
  );
}
