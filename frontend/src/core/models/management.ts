import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type ModelDraft = {
  name: string;
  display_name: string;
  provider: string;
  model: string;
  base_url?: string | null;
  api_key?: string;
  enabled: boolean;
  supports_vision: boolean | null;
  reasoning?: Record<string, unknown> | null;
  context_window: number | null;
  max_tokens: number | null;
};
export type ManagedModel = Omit<ModelDraft, "api_key"> & {
  revision: string;
  source: "managed";
  has_api_key: boolean;
  conflict?: boolean;
};
export type ManagedModelProvider = {
  id: string;
  display_name: string;
  requires_api_key: boolean;
  custom_endpoint: boolean;
};
export const loadManagedModelProviders = (signal?: AbortSignal) =>
  request<{ providers: ManagedModelProvider[] }>(
    "/providers",
    "GET",
    undefined,
    signal,
  );

export type ConfigModel = {
  name: string;
  display_name: string;
  model: string;
  source: "config";
  enabled: boolean;
};
export type SaveModelRequest = {
  config: ModelDraft;
  expected_revision: string | null;
};

async function request<T>(
  suffix: string,
  method: string,
  body?: SaveModelRequest,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/managed-models${suffix}`,
    {
      method,
      signal,
      ...(body
        ? {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        : {}),
    },
  );
  if (!response.ok)
    await throwGatewayApiError(response, "Model management request failed");
  return response.json() as Promise<T>;
}

export const loadManagedModels = (signal?: AbortSignal) =>
  request<{ models: (ManagedModel | ConfigModel)[] }>(
    "",
    "GET",
    undefined,
    signal,
  );
export const saveManagedModel = (body: SaveModelRequest) =>
  request<ManagedModel>("", "PUT", body);
export const testManagedModel = (
  body: SaveModelRequest,
  signal?: AbortSignal,
) =>
  request<{
    ok: boolean;
    message:
      | "success"
      | "tool_call_missing"
      | "connection_failed"
      | "authentication_failed"
      | "missing_api_key"
      | "response_limit";
  }>("/test", "POST", body, signal);

export function modelDraft(model?: ManagedModel): ModelDraft {
  return {
    name: model?.name ?? "",
    display_name: model?.display_name ?? "",
    provider: model?.provider ?? "openai",
    model: model?.model ?? "",
    ...(model?.provider === "openai-compatible"
      ? { base_url: model.base_url ?? "" }
      : {}),
    enabled: model?.enabled ?? true,
    supports_vision: model?.supports_vision ?? null,
    ...(model?.reasoning ? { reasoning: model.reasoning } : {}),
    context_window: model?.context_window ?? null,
    max_tokens: model?.max_tokens ?? null,
  };
}
