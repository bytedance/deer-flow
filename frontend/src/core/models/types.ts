export interface Model {
  id: string;
  name: string;
  model: string;
  display_name: string;
  description?: string | null;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
  supports_vision?: boolean;
}

export interface TokenUsageSettings {
  enabled: boolean;
}

export interface ModelsResponse {
  models: Model[];
  token_usage: TokenUsageSettings;
}

/** Full model configuration used by the admin settings page. */
export interface FullModelConfig {
  name: string;
  display_name?: string | null;
  description?: string | null;
  use: string;
  model: string;
  api_key?: string | null;
  api_base?: string | null;
  base_url?: string | null;
  timeout?: number | null;
  request_timeout?: number | null;
  max_retries?: number | null;
  max_tokens?: number | null;
  temperature?: number | null;
  supports_vision?: boolean;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
  when_thinking_enabled?: Record<string, unknown> | null;
  when_thinking_disabled?: Record<string, unknown> | null;
  /** Allow arbitrary provider-specific extra fields. */
  [key: string]: unknown;
}

export interface AdminModelsResponse {
  models: FullModelConfig[];
  token_usage: TokenUsageSettings;
}
