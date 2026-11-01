import type { DeviceDoc, DeviceSummary, Issue, Meta, SimResult } from "./types";

export class ApiError extends Error {
  issues: Issue[];
  constructor(message: string, issues: Issue[] = []) {
    super(message);
    this.issues = issues;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body?.detail;
    if (d && typeof d === "object") throw new ApiError(d.message || "Ошибка", d.issues || []);
    throw new ApiError(typeof d === "string" ? d : `Сервер ответил ${res.status}`);
  }
  return body as T;
}

const json = (b: unknown) => JSON.stringify(b);

export const api = {
  meta: () => call<Meta>("/api/rdl/meta"),
  devices: () => call<DeviceSummary[]>("/api/devices"),
  device: (id: string) => call<{ device: DeviceDoc; issues: Issue[]; builtin: boolean }>(`/api/devices/${id}`),
  validate: (doc: unknown) => call<{ ok: boolean; issues: Issue[] }>("/api/rdl/validate", { method: "POST", body: json(doc) }),
  compile: (doc: DeviceDoc) => call<{ ujin: any }>("/api/rdl/compile", { method: "POST", body: json(doc) }),
  simulate: (device: DeviceDoc, seconds: number, commands: { at: number; signal: string; value: unknown }[]) =>
    call<SimResult>("/api/rdl/simulate", { method: "POST", body: json({ device, seconds, commands }) }),
  save: (doc: DeviceDoc, force = false) =>
    call<{ ok: boolean }>(`/api/devices/${doc.id}${force ? "?force=true" : ""}`, { method: "PUT", body: json(doc) }),
  create: (doc: DeviceDoc) => call<{ ok: boolean }>("/api/devices", { method: "POST", body: json(doc) }),
  clone: (id: string, new_id: string, title: string) =>
    call<{ ok: boolean }>(`/api/devices/${id}/clone`, { method: "POST", body: json({ new_id, title }) }),
  reset: (id: string) => call<{ device: DeviceDoc }>(`/api/devices/${id}/reset`, { method: "POST" }),
  remove: (id: string) => call<{ ok: boolean }>(`/api/devices/${id}`, { method: "DELETE" }),
};
