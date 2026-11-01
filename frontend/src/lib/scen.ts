import { ApiError } from "./api";
import type { Issue, SignalSpec } from "./types";

export type Op = "==" | "!=" | ">" | ">=" | "<" | "<=";

export interface Trigger {
  type: "event" | "value" | "schedule" | "manual";
  instance?: string; event?: string; signal?: string; op?: Op; value?: number | string | null;
  at?: string; every?: number | null;
}
export interface Condition { instance: string; signal: string; op: Op; value: number | string }
export interface Action {
  type: "command" | "notify" | "wait";
  instance?: string; signal?: string; value?: number | string | null;
  delay?: number; hold?: number | null;
  text?: string; severity?: "info" | "warning" | "critical"; to?: "resident" | "uk" | "all";
  seconds?: number;
}
export interface Scenario {
  rsl?: "1.0"; id: string; title: string; description?: string; enabled?: boolean;
  triggers: Trigger[]; conditions?: Condition[]; match?: "all" | "any"; actions: Action[]; cooldown?: number;
}
export interface ScenarioSummary {
  id: string; title: string; enabled: boolean; description: string; valid: boolean;
  errors: number; warnings: number; trigger_types: string[]; sentence: string; builtin: boolean;
}
export interface CatInstance {
  id: string; title: string; room: string; device_id: string; device_title?: string;
  signals: SignalSpec[]; events: { name: string; title: string; severity: string }[];
  ujin: { ext?: string; sn?: string }; error: string;
}
export interface Conflict { scenarios: string[]; message: string }
export interface CheckResult {
  ok: boolean; issues: Issue[];
  text?: { sentence: string; when: string[]; if: string[]; do: string[] };
  conflicts?: Conflict[];
  ujin?: { exportable: boolean; conditions: string[]; set_signals: string[]; requests: any[]; skipped: string[] };
}

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new ApiError(typeof d === "string" ? d : d?.message ?? `Сервер ответил ${res.status}`, d?.issues ?? []);
  }
  return data as T;
}

export const scenApi = {
  catalog: () => call<{ instances: CatInstance[] }>("/api/scenarios/catalog"),
  list: () => call<{ items: ScenarioSummary[]; conflicts: Conflict[] }>("/api/scenarios"),
  get: (id: string) => call<CheckResult & { scenario: Scenario }>(`/api/scenarios/${id}`),
  check: (doc: Scenario) => call<CheckResult>("/api/scenarios/check", "POST", doc),
  save: (doc: Scenario, force = false) => call(`/api/scenarios/${doc.id}${force ? "?force=true" : ""}`, "PUT", doc),
  create: (doc: Scenario) => call("/api/scenarios", "POST", doc),
  enable: (id: string, enabled: boolean) => call(`/api/scenarios/${id}/enabled`, "POST", { enabled }),
  reset: (id: string) => call<{ scenario: Scenario }>(`/api/scenarios/${id}/reset`, "POST"),
  remove: (id: string) => call(`/api/scenarios/${id}`, "DELETE"),
};

export const OPS: { key: Op; trig: string; cond: string }[] = [
  { key: "==", trig: "становится", cond: "равно" },
  { key: "!=", trig: "перестаёт быть", cond: "не равно" },
  { key: ">", trig: "превышает", cond: "больше" },
  { key: ">=", trig: "достигает", cond: "не меньше" },
  { key: "<", trig: "опускается ниже", cond: "меньше" },
  { key: "<=", trig: "опускается до", cond: "не больше" },
];
