export interface Model {
  id: string;
  name: string;
  model: string;
  display_name: string;
  description?: string | null;
  base_url?: string | null;
  context_length?: number | null;
  modalities?: string[];
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

export interface DetectedModel {
  id: string;
  name: string;
  display_name: string;
  context_length?: number | null;
  modalities: string[];
  supports_thinking: boolean;
  supports_reasoning_effort: boolean;
  supports_vision: boolean;
}

export interface DetectModelsResponse {
  models: DetectedModel[];
  endpoint: string;
}

export interface ModelUpsertPayload {
  name: string;
  model: string;
  display_name?: string | null;
  description?: string | null;
  base_url?: string | null;
  api_key?: string | null;
  context_length?: number | null;
  temperature?: number | null;
  top_p?: number | null;
  frequency_penalty?: number | null;
  system_prompt?: string | null;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
  supports_vision?: boolean;
  modalities?: string[];
}
