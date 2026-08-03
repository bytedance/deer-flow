import type { BaseStream } from "@langchain/langgraph-sdk/react";

import type { AgentThreadState } from "../threads";

import { buildWriteFileDraftContent } from "./preview";
import { urlOfArtifact } from "./utils";

async function sha256OfText(content: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(content),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export const ARTIFACT_PREVIEW_MAX_BYTES = 1024 * 1024;

function parseContentRange(value: string | null) {
  const match = value?.match(/^bytes (?:(\d+)-(\d+)|\*)\/(\d+)$/);
  if (!match) return undefined;
  return {
    end: match[2] === undefined ? undefined : Number(match[2]),
    total: Number(match[3]),
  };
}

export async function loadArtifactContent({
  filepath,
  threadId,
  isMock,
  full = false,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
  full?: boolean;
}) {
  let enhancedFilepath = filepath;
  if (filepath.endsWith(".skill")) {
    enhancedFilepath = filepath + "/SKILL.md";
  }
  const url = urlOfArtifact({ filepath: enhancedFilepath, threadId, isMock });
  const response = await fetch(url, {
    cache: "no-store",
    headers: full
      ? undefined
      : { Range: `bytes=0-${ARTIFACT_PREVIEW_MAX_BYTES - 1}` },
  });
  const contentRange = parseContentRange(response.headers.get("Content-Range"));
  if (response.status === 416 && contentRange?.total === 0) {
    return {
      content: "",
      url,
      truncated: false,
      previewBytes: 0,
      totalBytes: 0,
      sha256: await sha256OfText(""),
    };
  }
  if (!response.ok) {
    throw new Error(`Failed to load artifact: ${response.status}`);
  }

  const bytes = await response.arrayBuffer();
  const truncated =
    !full &&
    response.status === 206 &&
    (contentRange?.end === undefined ||
      contentRange.total > contentRange.end + 1);
  // Streaming decode intentionally holds an incomplete trailing UTF-8 code
  // point instead of fabricating U+FFFD at the range boundary.
  const content = new TextDecoder().decode(bytes, { stream: truncated });
  const etag = response.headers.get("etag");
  const sha256 =
    etag?.match(/^"([0-9a-f]{64})"$/)?.[1] ??
    (!truncated ? await sha256OfText(content) : undefined);
  const contentLengthHeader = response.headers.get("Content-Length");
  const contentLength =
    contentLengthHeader === null ? undefined : Number(contentLengthHeader);
  return {
    content,
    url,
    sha256,
    truncated,
    previewBytes: bytes.byteLength,
    totalBytes:
      contentRange?.total ??
      (contentLength !== undefined && Number.isFinite(contentLength)
        ? contentLength
        : undefined),
  };
}

export function loadArtifactContentFromToolCall({
  url: urlString,
  thread,
}: {
  url: string;
  thread: BaseStream<AgentThreadState>;
}) {
  const draftContent = buildWriteFileDraftContent({
    filepath: urlString,
    messages: thread.messages,
  });
  if (draftContent !== undefined) {
    return draftContent;
  }

  const url = new URL(urlString);
  const toolCallId = url.searchParams.get("tool_call_id");
  const messageId = url.searchParams.get("message_id");
  if (messageId && toolCallId) {
    const message = thread.messages.find((message) => message.id === messageId);
    if (message?.type === "ai" && message.tool_calls) {
      const toolCall = message.tool_calls.find(
        (toolCall) => toolCall.id === toolCallId,
      );
      if (toolCall) {
        return toolCall.args.content;
      }
    }
  }
}
