import type { Message } from "@langchain/langgraph-sdk";

import { getBackendBaseURL } from "../config";
import { extractPresentFilesFromMessage } from "../messages/utils";
import { isStaticWebsiteOnly } from "../static-mode";
import type { AgentThreadState } from "../threads";

const EMPTY_ARTIFACT_PATHS: readonly string[] = [];

export function areStringArraysEqual(
  previous: readonly string[],
  next: readonly string[],
) {
  return (
    previous.length === next.length &&
    previous.every((value, index) => value === next[index])
  );
}

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

/**
 * Adds the `/mnt/` paths passed to `present_files` in `messages` to the
 * thread's artifact list. A reopened thread rebuilds its values from the
 * Gateway's POST /history head, which carries messages but not `artifacts`;
 * the backend fills `artifacts` from those same `present_files` calls, so the
 * messages are enough to recover the list. Returns `stateArtifacts` itself
 * when no message presents files.
 */
export function collectThreadArtifactPaths(
  stateArtifacts: readonly string[],
  messages: readonly Message[],
): readonly string[] {
  const presented = messages
    .flatMap((message) => extractPresentFilesFromMessage(message))
    .filter(
      (path): path is string =>
        typeof path === "string" && path.startsWith("/mnt/"),
    );
  if (presented.length === 0) {
    return stateArtifacts;
  }
  return [...new Set([...stateArtifacts, ...presented])];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  if (isStaticWebsiteOnly()) {
    return staticDemoArtifactURL({ filepath: absolutePath, threadId });
  }
  return `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/artifacts${encodeArtifactPath(absolutePath)}`;
}

export function resolveMarkdownArtifactURL(src: string, threadId: string) {
  const { path, suffix } = splitPathSuffix(src);
  // Markdown destinations already carry URL escapes; decode only at this
  // boundary before handing the raw path to the artifact URL builder.
  return `${resolveArtifactURL(decodeRelativeArtifactPath(path), threadId)}${suffix}`;
}

export interface ArtifactImageContext {
  filepath: string;
  threadId: string;
  isMock?: boolean;
}

export function resolveArtifactImageURL(
  src: string,
  { filepath, threadId, isMock }: ArtifactImageContext,
) {
  const { path, suffix } = splitPathSuffix(src);
  if (
    !path ||
    !filepath.startsWith("/mnt/") ||
    (path.startsWith("/") && !path.startsWith("/mnt/")) ||
    /^[a-z][a-z\d+.-]*:/i.test(path)
  ) {
    return src;
  }

  try {
    const decodedPath = decodeRelativeArtifactPath(path);
    if (decodedPath.includes("\\")) return src;
    // Skill previews read SKILL.md inside the archive, as loadArtifactContent does.
    const documentPath = filepath.endsWith(".skill")
      ? `${filepath}/SKILL.md`
      : filepath;
    const base = new URL(
      encodeArtifactPath(documentPath),
      "https://artifact.invalid",
    );
    const resolved = new URL(encodeArtifactPath(decodedPath), base);
    if (
      resolved.origin !== base.origin ||
      !resolved.pathname.startsWith("/mnt/")
    ) {
      return src;
    }
    return `${urlOfArtifact({
      filepath: decodeRelativeArtifactPath(resolved.pathname),
      threadId,
      isMock,
    })}${suffix}`;
  } catch {
    return src;
  }
}

function parseRelativeArtifactReference(src: string) {
  const { path: relativePath, suffix } = splitPathSuffix(src);
  const normalizedPath = relativePath.replace(/^(?:\.\/)+/, "");
  const decodedPath = decodeRelativeArtifactPath(normalizedPath);
  if (
    !normalizedPath ||
    normalizedPath.startsWith("/") ||
    /^[a-z][a-z\d+.-]*:/i.test(normalizedPath) ||
    normalizedPath.startsWith("//") ||
    normalizedPath.split("/").includes("..") ||
    decodedPath.split("/").includes("..")
  ) {
    return null;
  }
  return { decodedPath, suffix };
}

/**
 * True for a scheme-less relative path, including invalid artifact paths such
 * as `../report.md`. Message links in this category must either resolve to a
 * known artifact or render inert instead of navigating relative to the chat
 * route.
 */
export function isPotentialRelativeArtifactReference(src: string) {
  const { path } = splitPathSuffix(src);
  return (
    Boolean(path) &&
    !path.startsWith("/") &&
    !path.startsWith("//") &&
    !/^[a-z][a-z\d+.-]*:/i.test(path)
  );
}

/**
 * True for a scheme-less relative reference (`report.md`, `./out/a.png`)
 * that could name a thread artifact: no scheme, no leading `/`, no `..`
 * segment, and a non-empty path (so `#anchor` and `?query` are excluded).
 */
export function isRelativeArtifactReference(src: string) {
  return parseRelativeArtifactReference(src) !== null;
}

/**
 * Resolves a relative reference to this thread's artifact URL when it
 * suffix-matches exactly one artifact path. Returns `null` when `src` is not
 * a relative reference or when zero or several artifacts match.
 */
export function resolveRelativeArtifactURL(
  src: string,
  threadId: string,
  artifactPaths: readonly string[],
) {
  const reference = parseRelativeArtifactReference(src);
  if (!reference) {
    return null;
  }

  const matches = artifactPaths.filter((path) =>
    path.endsWith(`/${reference.decodedPath}`),
  );
  if (matches.length !== 1) {
    return null;
  }

  return `${resolveArtifactURL(matches[0]!, threadId)}${reference.suffix}`;
}

export function resolveMessageImageURL(
  src: string,
  threadId: string,
  artifactPaths: readonly string[],
) {
  if (src.startsWith("/mnt/")) {
    return resolveMarkdownArtifactURL(src, threadId);
  }

  return resolveRelativeArtifactURL(src, threadId, artifactPaths) ?? src;
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
