export type Group = "property" | "capability" | "setting" | "environment";
export type SigType = "bool" | "number" | "enum" | "text" | "button";

export interface SignalSpec {
  name: string;
  title: string;
  group: Group;
  type?: SigType;
  access?: "r" | "rw" | "w" | null;
  unit?: string;
  min?: number | null;
  max?: number | null;
  default?: number | string | boolean;
  options?: Record<string, string>;
  precision?: number;
  monotonic?: boolean;
  description?: string;
}

export interface ActionSpec {
  set?: string | null;
  to?: string | number | boolean | null;
  after?: number | null;
  hold?: number | null;
  then?: string | number | null;
  log?: string | null;
}

export interface RuleSpec {
  id?: string;
  title?: string;
  on: string;
  when?: string | null;
  do: ActionSpec[];
}

export interface EventSpec {
  name: string;
  title: string;
  when: string;
  severity: "info" | "warning" | "critical";
}

export interface DeviceDoc {
  rdl?: "1.0";
  id: string;
  title: string;
  model?: string;
  category?: string;
  icon?: string;
  description?: string;
  version?: string;
  signals: SignalSpec[];
  vars?: Record<string, number | string>;
  behavior?: RuleSpec[];
  events?: EventSpec[];
}

export interface Issue { path: string; message: string; severity: "error" | "warning" | "info"; }

export interface DeviceSummary {
  id: string;
  title: string;
  category: string;
  icon: string;
  description: string;
  model: string;
  groups: Partial<Record<Group, number>>;
  events: { name: string; title: string }[];
  valid: boolean;
  errors: number;
  builtin: boolean;
}

export interface SimResult {
  t: number[];
  series: Record<string, (number | string)[]>;
  events: { t: number; event: string; title: string; severity: string }[];
  log: string[];
  errors: string[];
}

export interface Meta {
  groups: Record<Group, string>;
  categories: Record<string, string>;
  types: Record<SigType, string>;
  functions: string[];
}
