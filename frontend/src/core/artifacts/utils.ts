import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";

export function isArtifactVirtualPath(path: string) {
  return path.startsWith("/mnt/") || path.startsWith("mnt/");
}

export function normalizeArtifactVirtualPath(path: string) {
  return path.startsWith("/") ? path : `/${path}`;
}

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
  const normalizedFilepath = normalizeArtifactVirtualPath(filepath);
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${threadId}/artifacts${normalizedFilepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${normalizedFilepath}${download ? "?download=true" : ""}`;
}

export function extractArtifactsFromThread(thread: AgentThread) {
  return thread.values.artifacts ?? [];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${normalizeArtifactVirtualPath(absolutePath)}`;
}
