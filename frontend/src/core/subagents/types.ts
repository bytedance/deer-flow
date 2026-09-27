export type SubagentSource = "builtin" | "config" | "managed";

export interface Subagent {
  name: string;
  display_name: string | null;
  description: string;
  system_prompt: string | null;
  tools: string[] | null;
  disallowed_tools: string[] | null;
  skills: string[] | null;
  model: string;
  max_turns: number;
  timeout_seconds: number;
  enabled: boolean;
  source: SubagentSource;
  editable: boolean;
  conflict: boolean;
  config_overrides: Record<string, unknown>;
}

export interface CreateManagedSubagentRequest {
  name: string;
  display_name?: string | null;
  description: string;
  system_prompt: string;
  tools?: string[] | null;
  disallowed_tools?: string[] | null;
  skills?: string[] | null;
  model?: string;
  max_turns?: number;
  timeout_seconds?: number;
  enabled?: boolean;
}

export type UpdateManagedSubagentRequest = Partial<
  Omit<CreateManagedSubagentRequest, "name">
>;
