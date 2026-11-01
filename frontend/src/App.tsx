import { useCallback, useEffect, useRef, useState } from "react";
import { ConstructorPage } from "./pages/ConstructorPage";
import { HomePage } from "./pages/HomePage";
import { EmulatorsPage } from "./pages/EmulatorsPage";
import { ScenariosPage } from "./pages/ScenariosPage";
import { UjinPage } from "./pages/UjinPage";

type Page = "home" | "devices" | "scenarios" | "emulators" | "ujin";
const PAGES: { key: Page; title: string }[] = [
  { key: "home", title: "Обзор" },
  { key: "devices", title: "Устройства" },
  { key: "scenarios", title: "Сценарии" },
  { key: "emulators", title: "Эмуляторы" },
  { key: "ujin", title: "Ujin OS" },
];

const fromHash = (): Page => (location.hash.replace("#/", "") as Page) || "home";

export default function App() {
  const [page, setPage] = useState<Page>(fromHash());
  const [toast, setToast] = useState("");
  const timer = useRef<number>();

  useEffect(() => {
    const h = () => setPage(fromHash());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);

  const notify = useCallback((t: string) => {
    setToast(t);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(""), 2600);
  }, []);

  return (
    <div className="grid h-full grid-rows-[56px_minmax(0,1fr)]">
      <header className="flex items-center gap-6 border-b border-line bg-ink px-5 text-white">
        <a href="#/home" className="flex items-baseline gap-1.5" aria-label="R Studio — на главную">
          <span className="text-[21px] font-bold tracking-tight">R</span>
          <span className="text-[21px] font-normal tracking-tight text-white/80">Studio</span>
        </a>
        <nav className="flex gap-1 text-sm" aria-label="Разделы">
          {PAGES.map((p) => (
            <a key={p.key} href={`#/${p.key}`} aria-current={page === p.key ? "page" : undefined}
              className={`rounded-md px-3 py-1.5 font-medium ${page === p.key ? "bg-white/15" : "text-white/70 hover:text-white"}`}>
              {p.title}
            </a>
          ))}
        </nav>
        <UjinBadge />
      </header>

      <div className="min-h-0">
        {page === "home" ? <HomePage notify={notify} />
          : page === "emulators" ? <EmulatorsPage notify={notify} />
          : page === "scenarios" ? <ScenariosPage notify={notify} />
          : page === "ujin" ? <UjinPage notify={notify} />
            : <ConstructorPage notify={notify} />}
      </div>

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-50 -translate-x-1/2">
        {toast && <div className="rounded-md bg-ink px-4 py-2 text-sm text-white shadow-lg">{toast}</div>}
      </div>
    </div>
  );
}

/** Индикатор в шапке: куда сейчас уходят значения. */
function UjinBadge() {
  const [mode, setMode] = useState<string>("off");
  useEffect(() => {
    const load = () => fetch("/api/ujin/state").then((r) => r.json()).then((s) => setMode(s.cfg.mode)).catch(() => {});
    load();
    const h = setInterval(load, 4000);
    return () => clearInterval(h);
  }, []);
  const text = mode === "live" ? "публикация на стенд Ujin" : mode === "dry" ? "Ujin: пробный режим" : "Ujin: выключено";
  return (
    <a href="#/ujin" className="ml-auto flex items-center gap-2 text-[13px] text-white/70 hover:text-white">
      <span className={`h-2 w-2 rounded-full ${mode === "live" ? "bg-[#7ee08a]" : mode === "dry" ? "bg-[#f2c14e]" : "bg-white/30"}`} aria-hidden />
      {text}
    </a>
  );
}
