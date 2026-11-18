import type { AIMessage, Message, ToolMessage } from "@langchain/langgraph-sdk";

import { getBackendBaseURL } from "../config";
import { indexToolResults } from "../messages/tool-result";
import { extractPresentFilesFromMessage } from "../messages/utils";
import { isStaticWebsiteOnly } from "../static-mode";
import type { AgentThreadState } from "../threads";

const EMPTY_ARTIFACT_PATHS: readonly string[] = [];
const SHARED_ARTIFACT_TOOL = "present_shared_artifact";

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

function normalizeSharedArtifactPath(path: string) {
  if (
    path.includes("\\") ||
    [...path].some((char) => char.charCodeAt(0) < 32)
  ) {
    return;
  }

  // Match the handoff's POSIX path normalization. / 与交接工具的 POSIX 路径规范化一致。
  const segments: string[] = [];
  for (const segment of path.split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") {
      if (segments.pop() === undefined) return;
    } else {
      segments.push(segment);
    }
  }

  const normalized = `/${segments.join("/")}`;
  return normalized.startsWith("/mnt/user-data/outputs/")
    ? normalized
    : undefined;
}

function extractSharedArtifactPaths(
  message: AIMessage,
  results: readonly ToolMessage[],
) {
  const paths: string[] = [];
  const calls = message.tool_calls ?? [];
  for (const { id, name, args } of calls) {
    if (
      name !== SHARED_ARTIFACT_TOOL ||
      !id ||
      calls.filter((call) => call.id === id).length !== 1
    ) {
      continue;
    }
    const { path, origin_thread_id, sha256 } = args ?? {};
    if (
      typeof path !== "string" ||
      typeof origin_thread_id !== "string" ||
      !origin_thread_id ||
      typeof sha256 !== "string" ||
      sha256.length !== 64 ||
      /[^0-9a-f]/.test(sha256)
    ) {
      continue;
    }

    // Match backend/packages/harness/deerflow/tools/artifact_handoff.py and
    // backend/tests/test_shared_artifact_handoff.py exactly.
    // Failures can also have a success status. / 失败回执也可能标为 success。
    const receipt = `Successfully presented shared artifact; origin_thread_id=${origin_thread_id}; sha256=${sha256}`;
    const matching = results.filter((result) => result.tool_call_id === id);
    if (
      matching.length === 0 ||
      matching.some((result) => {
        const metadata = result.additional_kwargs?.deerflow_tool_meta;
        return (
          (result.status !== undefined && result.status !== "success") ||
          (metadata !== undefined &&
            (typeof metadata !== "object" ||
              metadata === null ||
              !("status" in metadata) ||
              metadata.status !== "success")) ||
          (result.name != null && result.name !== SHARED_ARTIFACT_TOOL) ||
          result.content !== receipt
        );
      })
    ) {
      continue;
    }

    const normalized = normalizeSharedArtifactPath(path);
    if (normalized) paths.push(normalized);
  }
  return paths;
}

/**
 * Recovers artifact paths from history when the Gateway omits `artifacts`.
 * `present_files` contributes its paths directly. A shared artifact also needs
 * a confirmed handoff receipt. Returns `stateArtifacts` itself if neither
 * tool contributes paths.
 */
export function collectThreadArtifactPaths(
  stateArtifacts: readonly string[],
  messages: readonly Message[],
): readonly string[] {
  let toolResults: ReturnType<typeof indexToolResults<Message>> | undefined;
  const presented = messages
    .flatMap((message, index) => {
      const paths = extractPresentFilesFromMessage(message);
      if (
        message.type !== "ai" ||
        !message.tool_calls?.some((call) => call.name === SHARED_ARTIFACT_TOOL)
      ) {
        return paths;
      }
      const results = (toolResults ??= indexToolResults(messages)).get(index);
      if (!results) return paths;
      return [
        ...paths,
        ...extractSharedArtifactPaths(
          message,
          results.filter((result) => result.type === "tool"),
        ),
      ];
    })
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
