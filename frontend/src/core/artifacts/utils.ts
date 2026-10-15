import { isWorkspaceId } from "@/core/workspaces/request-scope";

import { getBackendBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";
import type { AgentThreadState } from "../threads";

const EMPTY_ARTIFACT_PATHS: readonly string[] = [];

function decodePathSegment(segment: string) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function splitPathSuffix(src: string) {
  const [path = ""] = src.split(/[?#]/, 1);
  return {
    path,
    suffix: src.slice(path.length),
  };
}

function encodeArtifactPath(filepath: string) {
  // This is a filesystem path, not a URL: a literal "%20" must stay part
  // of the filename after the server decodes the request path once.
  return filepath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

export function buildWriteFileArtifactURL({
  filepath,
  messageId,
  toolCallId,
}: {
  filepath: string;
  messageId?: string;
  toolCallId?: string;
}) {
  const url = new URL("write-file:/");
  url.pathname = filepath.replaceAll("%", "%25");
  if (messageId) {
    url.searchParams.set("message_id", messageId);
  }
  if (toolCallId) {
    url.searchParams.set("tool_call_id", toolCallId);
  }
  return url.toString();
}

function decodeRelativeArtifactPath(filepath: string) {
  return filepath.split("/").map(decodePathSegment).join("/");
}

export function urlOfArtifact({
  filepath,
  threadId,
  download = false,
  isMock = false,
  workspaceId,
}: {
  filepath: string;
  threadId: string;
  download?: boolean;
  isMock?: boolean;
  workspaceId?: string;
}) {
  if (
    workspaceId !== undefined &&
    (!isWorkspaceId(workspaceId) || isMock || isStaticWebsiteOnly())
  )
    throw new Error("Invalid scoped artifact target");
  if (isStaticWebsiteOnly()) {
    return staticDemoArtifactURL({ filepath, threadId, download });
  }
  const encodedThreadId = encodeURIComponent(threadId);
  const encodedFilepath = encodeArtifactPath(filepath);
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${encodedThreadId}/artifacts${encodedFilepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${encodedThreadId}/artifacts${encodedFilepath}${download ? "?download=true" : ""}${workspaceId === undefined ? "" : `${download ? "&" : "?"}workspace_id=${workspaceId}`}`;
}

export function urlOfArtifactArchive({
  threadId,
  runId,
}: {
  threadId: string;
  runId: string;
}) {
  return `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/artifacts/archive`;
}

export function extractArtifactsFromThread(thread: {
  values: Pick<AgentThreadState, "artifacts">;
}) {
  return thread.values.artifacts ?? EMPTY_ARTIFACT_PATHS;
}

function withWorkspaceSelector(url: string, workspaceId?: string) {
  if (workspaceId === undefined) return url;
  if (!isWorkspaceId(workspaceId) || isStaticWebsiteOnly())
    throw new Error("Invalid scoped artifact target");
  const hashAt = url.indexOf("#");
  const hash = hashAt < 0 ? "" : url.slice(hashAt);
  const address = hashAt < 0 ? url : url.slice(0, hashAt);
  const queryAt = address.indexOf("?");
  const path = queryAt < 0 ? address : address.slice(0, queryAt);
  const query = new URLSearchParams(
    queryAt < 0 ? "" : address.slice(queryAt + 1),
  );
  // Content-authored selectors are data, never a reason to leave this scope.
  query.set("workspace_id", workspaceId);
  return `${path}?${query}${hash}`;
}

function nativeArtifactTarget(src: string) {
  try {
    const origin = globalThis.location?.href ?? "http://localhost:2026/";
    const root = new URL(`${getBackendBaseURL()}/api/threads/`, origin);
    const url = new URL(src, origin);
    if (url.origin !== root.origin || !url.pathname.startsWith(root.pathname))
      return null;
    const match = /^([^/]+)\/artifacts(\/.*)$/.exec(
      url.pathname.slice(root.pathname.length),
    );
    return match ? { url, threadId: decodePathSegment(match[1]!) } : null;
  } catch {
    return null;
  }
}

/** Bind only native Gateway file URLs; web references stay untouched. */
export function bindArtifactURL(
  src: string,
  workspaceId?: string,
): string | undefined {
  if (workspaceId === undefined) return src;
  const target = nativeArtifactTarget(src);
  if (!target) return src;
  if (target.url.username || target.url.password) return undefined;
  return withWorkspaceSelector(src, workspaceId);
}

export function resolveArtifactURL(
  absolutePath: string,
  threadId: string,
  workspaceId?: string,
) {
  return urlOfArtifact({ filepath: absolutePath, threadId, workspaceId });
}

export function resolveMarkdownArtifactURL(
  src: string,
  threadId: string,
  workspaceId?: string,
) {
  const { path, suffix } = splitPathSuffix(src);
  // Decode URL-authored paths once; raw filesystem percent characters remain encoded.
  return withWorkspaceSelector(
    `${resolveArtifactURL(decodeRelativeArtifactPath(path), threadId)}${suffix}`,
    workspaceId,
  );
}

export function resolveMessageImageURL(
  src: string,
  threadId: string,
  artifactPaths: readonly string[],
  workspaceId?: string,
) {
  if (src.startsWith("/mnt/"))
    return resolveMarkdownArtifactURL(src, threadId, workspaceId);
  const { path: relativePath, suffix } = splitPathSuffix(src);
  const normalizedPath = relativePath.replace(/^(?:\.\/)+/, "");
  const decodedNormalizedPath = decodeRelativeArtifactPath(normalizedPath);
  if (
    !normalizedPath ||
    normalizedPath.startsWith("/") ||
    /^[a-z][a-z\d+.-]*:/i.test(normalizedPath) ||
    normalizedPath.startsWith("//") ||
    normalizedPath.split("/").includes("..")
  )
    return bindArtifactURL(src, workspaceId);
  const matches = artifactPaths.filter((path) =>
    path.endsWith(`/${decodedNormalizedPath}`),
  );
  if (matches.length !== 1) return bindArtifactURL(src, workspaceId);
  return withWorkspaceSelector(
    `${resolveArtifactURL(matches[0]!, threadId)}${suffix}`,
    workspaceId,
  );
}

/** Relative report resources resolve only inside the source thread's file route. */
export function resolveScopedArtifactResource(
  src: string,
  baseURL: string | undefined,
  workspaceId?: string,
): string | undefined {
  if (workspaceId === undefined || src.startsWith("#")) return src;
  const direct = nativeArtifactTarget(src);
  if (direct) return bindArtifactURL(src, workspaceId);
  const base = baseURL ? nativeArtifactTarget(baseURL) : null;
  if (src.startsWith("/mnt/"))
    return base
      ? resolveMarkdownArtifactURL(src, base.threadId, workspaceId)
      : undefined;
  if (src.startsWith("/") || /^[a-z][a-z\d+.-]*:/i.test(src)) return src;
  if (!base) return undefined;
  try {
    const destination = new URL(src, base.url);
    const target = nativeArtifactTarget(destination.href);
    if (target?.threadId !== base.threadId) return undefined;
    return bindArtifactURL(destination.href, workspaceId);
  } catch {
    return undefined;
  }
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
