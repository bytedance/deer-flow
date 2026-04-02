import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";

const THREAD_ARTIFACT_ROOTS = new Set(["outputs", "uploads", "workspace"]);

function normalizeArtifactFilepath(filepath: string, threadId: string) {
  const normalizedFilepath = filepath.replaceAll("\\", "/");

  if (normalizedFilepath.startsWith("/mnt/user-data/")) {
    return normalizedFilepath;
  }

  if (normalizedFilepath.startsWith("mnt/user-data/")) {
    return `/${normalizedFilepath}`;
  }

  const threadDataMarker = `/threads/${threadId}/user-data/`;
  const markerIndex = normalizedFilepath.indexOf(threadDataMarker);

  if (markerIndex === -1) {
    return normalizedFilepath;
  }

  const relativePath = normalizedFilepath.slice(
    markerIndex + threadDataMarker.length,
  );
  const [root, ...segments] = relativePath.split("/");

  if (!root || !THREAD_ARTIFACT_ROOTS.has(root)) {
    return normalizedFilepath;
  }

  return `/mnt/user-data/${root}${segments.length > 0 ? `/${segments.join("/")}` : ""}`;
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
  const normalizedFilepath = normalizeArtifactFilepath(filepath, threadId);

  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${threadId}/artifacts${normalizedFilepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${normalizedFilepath}${download ? "?download=true" : ""}`;
}

export function extractArtifactsFromThread(thread: AgentThread) {
  return thread.values.artifacts ?? [];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${normalizeArtifactFilepath(absolutePath, threadId)}`;
}
