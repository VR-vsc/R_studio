import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import type { SignalSpec } from "./types";

export interface EmuInstance {
  id: string;
  device_id: string;
  title: string;
  room: string;
  ujin: { ext?: string; sn?: string };
  error: string;
  model?: string;
  category?: string;
  device_title?: string;
  signals?: SignalSpec[];
  events?: { name: string; title: string; severity: string }[];
  values?: Record<string, number | string>;
  active?: string[];
}

export interface EmuEvent {
  id: number; t: number; wall: number; instance: string; instance_title: string; room: string;
  device_id: string; event: string; title: string; severity: "info" | "warning" | "critical";
}

export interface EmuLog { t: number; instance: string; text: string }

export interface RunStep { i: number; t: number; text: string; status: "waiting" | "done" | "failed"; error?: string }
export interface Run {
  id: number; scenario: string; title: string; t: number; reason: string;
  conditions: { text: string; ok: boolean; actual: string }[];
  steps: RunStep[]; status: "running" | "done" | "failed" | "skipped"; note: string;
}
export interface Note { id: number; t: number; scenario: string; title: string; text: string; severity: "info" | "warning" | "critical"; to: string }

export interface DemoState { story: string; title?: string; step?: number; total?: number; caption: string; done: boolean; stopped?: boolean }

export interface EmuState {
  demo?: DemoState | null;
  t: number;
  day_start: number;
  runs: Run[];
  notes: Note[];
  running: boolean;
  speed: number;
  instances: EmuInstance[];
  events: EmuEvent[];
  logs: EmuLog[];
}

async function call<T>(path: string, method = "POST", body?: unknown): Promise<T> {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : `Сервер ответил ${res.status}`);
  return data as T;
}

export const emuApi = {
  act: (iid: string, signal: string, value: unknown) => call(`/api/emu/instances/${iid}/act`, "POST", { signal, value }),
  clock: (c: { running?: boolean; speed?: number }) => call("/api/emu/clock", "POST", c),
  step: (n: number) => call(`/api/emu/step?n=${n}`),
  restart: (iid?: string) => call(`/api/emu/restart${iid ? `?iid=${iid}` : ""}`),
  reset: () => call("/api/emu/reset"),
  add: (cfg: { id: string; device_id: string; title: string; room: string }) => call<EmuInstance>("/api/emu/instances", "POST", cfg),
  update: (iid: string, patch: Partial<EmuInstance>) => call<EmuInstance>(`/api/emu/instances/${iid}`, "PATCH", patch),
  remove: (iid: string) => call(`/api/emu/instances/${iid}`, "DELETE"),
  runScenario: (sid: string) => call(`/api/scenarios/${sid}/run`),
};

/** Живое состояние квартиры через WebSocket (с переподключением). */
export function useEmulation() {
  const [state, setState] = useState<EmuState | null>(null);
  const [connected, setConnected] = useState(false);
  const flash = useRef<Record<string, number>>({});
  const [, force] = useState(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    let retry: number | undefined;
    const connect = () => {
      const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/emu/ws`;
      ws = new WebSocket(url);
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!stop) retry = window.setTimeout(connect, 1500);
      };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.type === "snapshot") {
          fetch("/api/scenarios/engine").then((r) => r.json()).then((e) =>
            setState((prev) => prev && { ...prev, runs: e.runs ?? [], notes: e.notifications ?? [] })).catch(() => {});
        }
        setState((prev) => reduce(prev, msg, flash.current));
        if (msg.type === "values") force((x) => x + 1);
      };
    };
    connect();
    return () => { stop = true; window.clearTimeout(retry); ws?.close(); };
  }, []);

  const recentlyChanged = useCallback((iid: string, sig: string) => {
    const at = flash.current[`${iid}.${sig}`];
    return at !== undefined && Date.now() - at < 900;
  }, []);

  return { state, connected, recentlyChanged };
}

function reduce(prev: EmuState | null, msg: any, flash: Record<string, number>): EmuState | null {
  switch (msg.type) {
    case "snapshot":
      return { t: msg.t, day_start: msg.day_start ?? 0, running: msg.running, speed: msg.speed, instances: msg.instances,
        events: msg.events ?? [], logs: prev?.logs ?? [], runs: prev?.runs ?? [], notes: prev?.notes ?? [], demo: prev?.demo ?? null };
    case "values": {
      if (!prev) return prev;
      const now = Date.now();
      const instances = prev.instances.map((i) => {
        const ch = msg.changes[i.id];
        const active = msg.active?.[i.id] ?? i.active;
        if (!ch) return active === i.active ? i : { ...i, active };
        Object.keys(ch).forEach((k) => { flash[`${i.id}.${k}`] = now; });
        return { ...i, values: { ...i.values, ...ch }, active };
      });
      return { ...prev, t: msg.t, instances };
    }
    case "event":
      return prev && { ...prev, events: [...prev.events, msg as EmuEvent].slice(-200) };
    case "log":
      return prev && { ...prev, logs: [...prev.logs, msg as EmuLog].slice(-200) };
    case "run": {
      if (!prev) return prev;
      const others = prev.runs.filter((r) => r.id !== msg.id);
      return { ...prev, runs: [...others, msg as Run].sort((a, b) => a.id - b.id).slice(-100) };
    }
    case "demo":
      return prev && { ...prev, demo: msg.stopped ? null : (msg as DemoState) };
    case "notify":
      return prev && { ...prev, notes: [...prev.notes, msg as Note].slice(-100) };
    case "clock":
      return prev && { ...prev, t: msg.t, running: msg.running, speed: msg.speed };
    default:
      return prev;
  }
}
