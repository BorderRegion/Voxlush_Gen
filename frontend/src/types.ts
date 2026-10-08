import type { components } from "./generated/api-schema";

// Backend OpenAPI owns states, request actions and typed wire records.
export type Overview = components["schemas"]["Overview"];
export type Sample = components["schemas"]["SampleSummary"];
export type Queue = components["schemas"]["Queue"];
export type Command = components["schemas"]["CommandResult"];
export type CommandInput = components["schemas"]["CommandCreate"];
export type CommandAction = CommandInput["action"];
export interface Campaign {
  campaign_id: string;
  name: string;
  state: string;
  target: number;
  accepted_unique: number;
  config_revision: number;
  requests_used: number;
  requests_limit: number;
}
export interface Artifact {
  artifact_id: string;
  name: string;
}
export interface SampleDetail extends Sample {
  task: Record<string, unknown>;
  artifacts: Artifact[];
  events: Record<string, unknown>[];
  attempts: Record<string, unknown>[];
  [key: string]: unknown;
}
export interface Coverage {
  family_id: string;
  name: string;
  scene_type: string;
  target: number;
  accepted: number;
  active: number;
  rejected: number;
  duplicate: number;
  debt: number;
  qualification: string;
  reason_code: string | null;
}
export interface Metric {
  minute: number;
  accepted: number;
  requests: number;
  active_requests: number;
  effective_cap: number;
}
export interface ExportJob {
  export_id: string;
  status: string;
  reason?: string | null;
  artifact_id?: string | null;
  result?: { artifacts?: Artifact[] };
  [key: string]: unknown;
}
export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}
