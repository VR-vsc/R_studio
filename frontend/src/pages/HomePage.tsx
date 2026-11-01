import { ArrowUpRight, Play } from "lucide-react";
import { useEffect, useState } from "react";

interface Overview {
  devices: number; instances: number; rooms: number; scenarios: number; scenarios_on: number;
  runs: number; notifications: number; events: number;
  ujin: { mode: string; bound: number; published: number; ready: string | null };
}
interface Story { id: string; title: string; about: string; steps: number; seconds: number }

const UJIN_MODE: Record<string, string> = { off: "выключено", dry: "пробный режим", live: "публикация на стенд" };

/** Главная: как устроена работа в R Studio и быстрый вход в демо. */
export function HomePage({ notify }: { notify: (t: string) => void }) {
  const [o, setO] = useState<Overview | null>(null);
  const [stories, setStories] = useState<Story[]>([]);

  useEffect(() => {
    const load = () => fetch("/api/overview").then((r) => r.json()).then(setO).catch(() => {});
    load();
    fetch("/api/demo").then((r) => r.json()).then((d) => setStories(d.stories)).catch(() => {});
    const h = setInterval(load, 3000);
    return () => clearInterval(h);
  }, []);

  const start = async (id: string) => {
    const r = await fetch(`/api/demo/${id}/start`, { method: "POST" });
    if (!r.ok) return notify("Не удалось запустить демо");
    location.hash = "#/emulators";
  };

  const steps = [
    { href: "#/devices", verb: "Опишите", what: "устройство", text: "Что оно измеряет, чем управляется и как себя ведёт — на одном языке RDL. Форма для всех, код для разработчика.",
      stat: o ? `${o.devices} устройств в библиотеке` : "…" },
    { href: "#/scenarios", verb: "Свяжите", what: "правилом", text: "«Когда → И если → То» из выпадающих списков. Проверка ошибок, конфликтов и зацикливания, пересказ одной фразой.",
      stat: o ? `${o.scenarios_on} из ${o.scenarios} сценариев включены` : "…" },
    { href: "#/emulators", verb: "Проверьте", what: "на эмуляторах", text: "Живая квартира: налейте воду, напустите дым, откройте окно — и смотрите, что сделали сценарии и почему.",
      stat: o ? `${o.instances} устройств в ${o.rooms} комнатах · ${o.runs} запусков` : "…" },
    { href: "#/ujin", verb: "Отправьте", what: "в Ujin OS", text: "Значения привязанных устройств уходят на стенд, простые сценарии — в autoscripts жителя. Всё видно в журнале.",
      stat: o ? `${o.ujin.bound} на стенде · ${UJIN_MODE[o.ujin.mode] ?? o.ujin.mode}` : "…" },
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1180px] px-8 pb-12 pt-10">
        <h1 className="max-w-[18ch] text-[44px] font-semibold leading-[1.05] tracking-tight">
          Умный дом, который можно проверить до того, как он появится.
        </h1>
        <p className="mt-4 max-w-[62ch] text-[16px] text-mute">
          R Studio — редактор сценариев для устройств на платформе Ujin OS. Описываете устройства на одном языке,
          связываете их правилами и проверяете на эмуляторах, без железа и без кода.
        </p>

        <ol className="mt-10 grid grid-cols-4 gap-px overflow-hidden rounded-lg border border-line bg-line">
          {steps.map((s, i) => (
            <li key={s.href} className="bg-paper">
              <a href={s.href} className="group flex h-full flex-col p-5 hover:bg-white">
                <span className="text-[13px] tabular-nums text-mute">{i + 1}</span>
                <span className="mt-3 text-[24px] font-semibold leading-tight">{s.verb}</span>
                <span className="text-[24px] leading-tight text-mute">{s.what}</span>
                <span className="mt-3 flex-1 text-[14px] leading-relaxed">{s.text}</span>
                <span className="mt-5 flex items-center justify-between gap-2 border-t border-line pt-3 text-[13px] text-mute group-hover:text-ink">
                  {s.stat} <ArrowUpRight size={15} aria-hidden />
                </span>
              </a>
            </li>
          ))}
        </ol>

        <section aria-labelledby="demo-h" className="mt-12">
          <h2 id="demo-h" className="text-[20px] font-semibold">Показать за минуту</h2>
          <p className="mt-1 text-[14px] text-mute">Готовые истории: квартира начинается с чистого листа, «мир вокруг» меняется сам, а подписи объясняют, что сделали сценарии.</p>
          <div className="mt-4 grid grid-cols-4 gap-3">
            {stories.map((s) => (
              <button key={s.id} onClick={() => start(s.id)}
                className="group flex flex-col rounded-lg border border-line bg-paper p-4 text-left hover:border-ink">
                <span className="font-semibold">{s.title}</span>
                <span className="mt-1 flex-1 text-[13px] leading-snug text-mute">{s.about}</span>
                <span className="mt-4 flex items-center gap-1.5 text-[13px] font-medium text-g-capability">
                  <Play size={14} aria-hidden /> Запустить · ~{s.seconds} с
                </span>
              </button>
            ))}
          </div>
        </section>

        {o && (
          <section aria-label="Сейчас в квартире" className="mt-12 flex flex-wrap gap-x-10 gap-y-3 border-t border-line pt-5 text-[14px]">
            <span><span className="text-[22px] font-semibold tabular-nums">{o.events}</span> <span className="text-mute">событий устройств</span></span>
            <span><span className="text-[22px] font-semibold tabular-nums">{o.runs}</span> <span className="text-mute">запусков сценариев</span></span>
            <span><span className="text-[22px] font-semibold tabular-nums">{o.notifications}</span> <span className="text-mute">уведомлений жителю и УК</span></span>
            <span><span className="text-[22px] font-semibold tabular-nums">{o.ujin.published}</span> <span className="text-mute">значений отправлено в Ujin</span></span>
          </section>
        )}
      </div>
    </div>
  );
}
