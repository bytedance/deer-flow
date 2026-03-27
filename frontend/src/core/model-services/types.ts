export type ProviderModality = "text" | "image" | "video" | "audio";
export type ProviderType =
  | "openai-compatible"
  | "anthropic-native"
  | "gemini-native"
  | "custom";
export type ApiKeyMode = "preserve" | "replace" | "clear";

export interface ModelServiceModel {
  id: string;
  name: string;
  display_name?: string | null;
  model: string;
  enabled: boolean;
  modalities: ProviderModality[];
  supports_thinking: boolean;
  supports_reasoning_effort: boolean;
  supports_vision: boolean;
  use_responses_api?: boolean | null;
  output_version?: string | null;
  extra_body?: Record<string, unknown> | null;
  max_tokens?: number | null;
  temperature?: number | null;
  description?: string | null;
}

export interface ModelServiceProvider {
  id: string;
  name: string;
  provider_type: ProviderType;
  enabled: boolean;
  base_url: string;
  api_key_masked?: string | null;
  api_key_configured: boolean;
  api_key_input?: string;
  api_key_mode?: ApiKeyMode;
  headers: Record<string, string>;
  homepage?: string | null;
  notes?: string | null;
  modalities: ProviderModality[];
  models: ModelServiceModel[];
}

export interface ModelServiceDefaults {
  text_model_name?: string | null;
  image_model_name?: string | null;
  video_model_name?: string | null;
  audio_model_name?: string | null;
}

export interface RegisteredModel {
  id: string;
  name: string;
  display_name?: string | null;
  model: string;
  description?: string | null;
  provider?: string | null;
  provider_label?: string | null;
  provider_url?: string | null;
  provider_id?: string | null;
  modalities: ProviderModality[];
  supports_thinking: boolean;
  supports_reasoning_effort: boolean;
  supports_vision: boolean;
  enabled: boolean;
  source: "config" | "provider";
}

export interface ModelServicesConfig {
  providers: ModelServiceProvider[];
  defaults: ModelServiceDefaults;
  registered_models: RegisteredModel[];
}

export interface ProviderTestResult {
  ok: boolean;
  models_url_ok: boolean;
  chat_ok: boolean;
  discovered_models: string[];
  message: string;
}

export interface DiscoveredProviderModel {
  id: string;
  display_name: string;
  owned_by?: string | null;
  already_configured: boolean;
}

export interface DiscoveredProviderModelsResponse {
  models: DiscoveredProviderModel[];
}

export interface ModelServiceProviderWrite extends Omit<ModelServiceProvider, "api_key_masked" | "api_key_configured" | "api_key_input"> {
  api_key?: string;
  api_key_mode: ApiKeyMode;
}

export interface ModelServicesConfigWrite {
  providers: ModelServiceProviderWrite[];
  defaults: ModelServiceDefaults;
}
