import { getBackendBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";
import type { AgentThreadState } from "../threads";

const EMPTY_ARTIFACT_PATHS: readonly string[] = [];

function encodeArtifactPath(filepath: string) {
  return filepath.split("/").map(encodeURIComponent).join("/");
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
  if (isStaticWebsiteOnly()) {
    return staticDemoArtifactURL({ filepath, threadId, download });
  }
  const encodedThreadId = encodeURIComponent(threadId);
  const encodedFilepath = encodeArtifactPath(filepath);
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${encodedThreadId}/artifacts${encodedFilepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${encodedThreadId}/artifacts${encodedFilepath}${download ? "?download=true" : ""}`;
}

export function extractArtifactsFromThread(thread: {
  values: Pick<AgentThreadState, "artifacts">;
}) {
  return thread.values.artifacts ?? EMPTY_ARTIFACT_PATHS;
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  if (isStaticWebsiteOnly()) {
    return staticDemoArtifactURL({ filepath: absolutePath, threadId });
  }
  return `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/artifacts${encodeArtifactPath(absolutePath)}`;
}

export function resolveMessageImageURL(
  src: string,
  threadId: string,
  artifactPaths: readonly string[],
) {
  if (src.startsWith("/mnt/")) {
    return resolveArtifactURL(src, threadId);
  }

  const [relativePath = ""] = src.split(/[?#]/, 1);
  const normalizedPath = relativePath.replace(/^(?:\.\/)+/, "");
  if (
    !normalizedPath ||
    normalizedPath.startsWith("/") ||
    /^[a-z][a-z\d+.-]*:/i.test(normalizedPath) ||
    normalizedPath.startsWith("//") ||
    normalizedPath.split("/").includes("..")
  ) {
    return src;
  }

  const matches = artifactPaths.filter((path) =>
    path.endsWith(`/${normalizedPath}`),
  );
  if (matches.length !== 1) {
    return src;
  }

  return `${resolveArtifactURL(matches[0]!, threadId)}${src.slice(relativePath.length)}`;
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
  const demoPath = encodeArtifactPath(filepath.replace(/^\/mnt\//, "/"));
  return `${getBackendBaseURL()}/demo/threads/${encodeURIComponent(threadId)}${demoPath}${download ? "?download=true" : ""}`;
}
