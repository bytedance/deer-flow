import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export const DEFAULT_MAX_SUGGESTIONS = 3;

export interface SuggestionsConfigResponse {
  enabled: boolean;
  max_suggestions: number;
}

export async function loadSuggestionsConfig(): Promise<SuggestionsConfigResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/suggestions/config`);
  if (!response.ok) {
    if (response.status === 404) {
      // Fallback to true if the backend is older
      return { enabled: true, max_suggestions: DEFAULT_MAX_SUGGESTIONS };
    }
    throw new Error(
      `Failed to load suggestions config: ${response.statusText}`,
    );
  }
  return response.json() as Promise<SuggestionsConfigResponse>;
}
