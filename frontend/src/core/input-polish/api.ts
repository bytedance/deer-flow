import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type InputPolishRequest = {
  text: string;
  locale?: string;
  thread_id?: string;
};

export type InputPolishResponse = {
  rewritten_text: string;
  changed: boolean;
};

export async function polishInputDraft(
  request: InputPolishRequest,
  options?: { signal?: AbortSignal },
): Promise<InputPolishResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/input-polish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: options?.signal,
  });

  if (!response.ok) {
    await throwGatewayApiError(response, "Failed to polish input");
  }

  return response.json() as Promise<InputPolishResponse>;
}
