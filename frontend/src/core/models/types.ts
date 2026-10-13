export type ModelThinkingMode = "unsupported" | "optional" | "required";

export interface ModelReasoningEffortCapabilities {
  /** Accepted effort values in the provider's own vocabulary, in display order. */
  values: string[];
  /** Effort the Gateway applies when the caller does not choose one. */
  default: string | null;
  /** DeerFlow generic value (minimal/low/medium/high) -> provider value. */
  aliases: Record<string, string>;
}

/**
 * Normalized reasoning capability contract projected by `/api/models`
 * (issue #5073). Legacy profiles report `source: "legacy"` with the generic
 * effort vocabulary, which is what the UI used to assume from the booleans.
 */
export interface ModelReasoningCapabilities {
  thinking: ModelThinkingMode;
  effort: ModelReasoningEffortCapabilities | null;
  history: "preserve" | "clear" | null;
  source: "legacy" | "contract";
}

export interface Model {
  id: string;
  name: string;
  model: string;
  display_name: string;
  description?: string | null;
  /** @deprecated derived from `reasoning`; kept for older Gateways. */
  supports_thinking?: boolean;
  /** @deprecated derived from `reasoning`; kept for older Gateways. */
  supports_reasoning_effort?: boolean;
  reasoning?: ModelReasoningCapabilities | null;
}

export interface TokenUsageSettings {
  enabled: boolean;
}

export interface ModelsResponse {
  models: Model[];
  token_usage: TokenUsageSettings;
}
