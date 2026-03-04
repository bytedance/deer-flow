export type ProviderId =
  | "openai"
  | "anthropic"
  | "gemini"
  | "deepseek"
  | "kimi"
  | "zai"
  | "minimax"
  | "epfl-rcp";

export interface ProviderModel {
  id: string;
  provider: ProviderId;
  model_id: string;
  display_name: string;
  description?: string | null;
  supports_thinking?: boolean;
  thinking_enabled?: boolean;
  supports_vision?: boolean;
  supports_adaptive_thinking?: boolean;
  adaptive_thinking_efforts?: string[];
  default_thinking_effort?: string | null;
  tier?: string | null;
  tier_label?: string | null;
}

export interface ProviderCatalog {
  id: ProviderId;
  display_name: string;
  description?: string | null;
  enabled_by_default: boolean;
  requires_api_key: boolean;
  models: ProviderModel[];
}

export interface RuntimeModelSpec {
  provider: ProviderId;
  model_id: string;
  tier?: string | null;
  thinking_effort?: string;
  api_key?: string;

  supports_vision?: boolean;
}
