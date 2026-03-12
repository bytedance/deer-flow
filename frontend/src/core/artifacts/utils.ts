import { authFetch } from "../auth/fetch";
import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";

export function urlOfArtifact({
  filepath,
  threadId,
  download = false,
}: {
  filepath: string;
  threadId: string;
  download?: boolean;
}) {
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
}

/**
 * Download an artifact using authenticated fetch, then trigger a browser download.
 */
export async function downloadArtifact({
  filepath,
  threadId,
}: {
  filepath: string;
  threadId: string;
}) {
  const url = urlOfArtifact({ filepath, threadId, download: true });
  const response = await authFetch(url);
  if (!response.ok) {
    throw new Error(`Download failed: ${response.statusText}`);
  }
  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = filepath.split("/").pop() ?? "download";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(blobUrl);
}

export function extractArtifactsFromThread(thread: AgentThread) {
  return thread.values.artifacts ?? [];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${absolutePath}`;
}
