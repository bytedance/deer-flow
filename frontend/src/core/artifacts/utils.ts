import { getBackendBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";
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
  if (isStaticWebsiteOnly()) {
    return staticDemoArtifactURL({
      filepath: normalizedFilepath,
      threadId,
      download,
    });
  }
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${threadId}/artifacts${normalizedFilepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${normalizedFilepath}${download ? "?download=true" : ""}`;
}

export function extractArtifactsFromThread(thread: AgentThread) {
  return thread.values.artifacts ?? [];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  const normalizedFilepath = normalizeArtifactVirtualPath(absolutePath);
  if (isStaticWebsiteOnly()) {
    return staticDemoArtifactURL({ filepath: normalizedFilepath, threadId });
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${normalizedFilepath}`;
}

function staticDemoArtifactURL({
  filepath,
  threadId,
  download = false,
}: {
  filepath: string;
  threadId: string;
  download?: boolean;
}) {
  const demoPath = filepath.replace(/^\/mnt\//, "/");
  return `${getBackendBaseURL()}/demo/threads/${threadId}${demoPath}${download ? "?download=true" : ""}`;
}
