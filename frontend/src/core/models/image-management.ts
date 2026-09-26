import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type ImageProvider = "openai" | "gemini" | "minimax";
export type ImageConnectionStatus =
  | "not_configured"
  | "invalid_config"
  | "configured_unverified"
  | "ready"
  | "unreachable";

export type ImageProfileDraft = {
  name: string;
  display_name: string;
  provider: ImageProvider;
  model: string;
  base_url: string | null;
  size: string | null;
  enabled: boolean;
  api_key?: string;
};

export type ImageProfile = Omit<ImageProfileDraft, "api_key"> & {
  source: "managed" | "config";
  has_api_key: boolean;
  revision?: string;
  verified_generation: boolean;
  verified_edit: boolean;
  last_generation_result?: string | null;
  last_edit_result?: string | null;
};

export type ImageStatus = {
  status: ImageConnectionStatus;
  source: "managed" | "sandbox_environment" | null;
  provider: ImageProvider | null;
  model: string | null;
  has_api_key: boolean;
  supports_generation: boolean;
  supports_edit: boolean;
};

export type ImageCatalog = {
  profiles: ImageProfile[];
  status: ImageStatus;
};

async function request<T>(
  suffix: string,
  method: "GET" | "PUT" | "POST",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/image-generation${suffix}`,
    {
      method,
      signal,
      ...(body === undefined
        ? {}
        : {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
    },
  );
  if (!response.ok)
    await throwGatewayApiError(response, "Image model request failed");
  return response.json() as Promise<T>;
}

export const loadImageProfiles = (signal?: AbortSignal) =>
  request<ImageCatalog>("/profiles", "GET", undefined, signal);

export const saveImageProfile = (
  config: ImageProfileDraft,
  expectedRevision: string | null,
) =>
  request<ImageProfile>("/profiles", "PUT", {
    config,
    expected_revision: expectedRevision,
  });

export const testImageProfile = (
  name: string,
  revision: string,
  operation: "generation" | "edit",
  signal?: AbortSignal,
) =>
  request<{ ok: boolean; message: string }>(
    `/profiles/${encodeURIComponent(name)}/test/${operation}`,
    "POST",
    { expected_revision: revision },
    signal,
  );

export function imageProfileDraft(profile?: ImageProfile): ImageProfileDraft {
  return {
    name: profile?.name ?? "",
    display_name: profile?.display_name ?? "",
    provider: profile?.provider ?? "openai",
    model: profile?.model ?? "",
    base_url: profile?.base_url ?? null,
    size: profile?.size ?? null,
    enabled: profile?.enabled ?? true,
  };
}
