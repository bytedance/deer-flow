import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";

export function urlOfArtifact({
  filepath,
  threadId,
  download = false,
  isMock = false,
}: {
  filepath: string;
  threadId: string;
  download?: boolean;
  isMock?: boolean;
}) {
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
}

export function extractArtifactsFromThread(thread: AgentThread) {
  return thread.values.artifacts ?? [];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${absolutePath}`;
}

/**
 * Save content to an artifact file on the backend.
 * Only works for files under /mnt/user-data/outputs/.
 */
export async function saveArtifact({
  filepath,
  threadId,
  content,
}: {
  filepath: string;
  threadId: string;
  content: string;
}): Promise<{ success: boolean; path: string }> {
  // filepath is like /mnt/user-data/outputs/dashboard.json
  // The API expects the path without leading slash
  const apiPath = filepath.startsWith("/") ? filepath.slice(1) : filepath;
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/save-artifact/${apiPath}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Save failed" }));
    throw new Error((error as { detail?: string }).detail ?? "Save failed");
  }

  return response.json() as Promise<{ success: boolean; path: string }>;
}
