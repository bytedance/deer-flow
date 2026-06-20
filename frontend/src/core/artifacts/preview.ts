export type ArtifactViewMode = "code" | "preview";

type ArtifactPreviewMessage = {
  type?: string;
  id?: string;
  name?: string | null;
  tool_call_id?: string;
  content?: unknown;
  tool_calls?: Array<{
    id?: string;
    name?: string;
    args?: Record<string, unknown>;
  }>;
};

export function isWriteFileArtifact(filepath: string) {
  return filepath.startsWith("write-file:");
}

function hasSuccessfulWriteResult(toolResult: string | undefined) {
  return toolResult?.trim() === "OK";
}

function hasFailedWriteResult(toolResult: string | undefined) {
  return (
    typeof toolResult === "string" && !hasSuccessfulWriteResult(toolResult)
  );
}

function getTextContent(content: unknown) {
  if (typeof content === "string") {
    return content.trim();
  }
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (
          typeof part === "object" &&
          part !== null &&
          "text" in part &&
          typeof part.text === "string"
        ) {
          return part.text;
        }
        return "";
      })
      .join("")
      .trim();
  }
  return undefined;
}

function findToolResult(
  toolCallId: string,
  messages: ArtifactPreviewMessage[],
) {
  for (const message of messages) {
    if (message.type === "tool" && message.tool_call_id === toolCallId) {
      return getTextContent(message.content);
    }
  }
  return undefined;
}

function parseWriteFileArtifact(filepath: string) {
  if (!isWriteFileArtifact(filepath)) {
    return undefined;
  }
  try {
    const url = new URL(filepath);
    return {
      path: decodeURIComponent(url.pathname),
      messageId: url.searchParams.get("message_id") ?? undefined,
      toolCallId: url.searchParams.get("tool_call_id") ?? undefined,
    };
  } catch {
    return undefined;
  }
}

export function buildWriteFileDraftContent({
  filepath,
  messages,
}: {
  filepath: string;
  messages: ArtifactPreviewMessage[];
}) {
  const target = parseWriteFileArtifact(filepath);
  if (!target) {
    return undefined;
  }

  let draft = "";
  let hasDraft = false;

  for (const message of messages) {
    if (message.type !== "ai") {
      continue;
    }

    for (const toolCall of message.tool_calls ?? []) {
      const args = toolCall.args ?? {};
      if (
        toolCall.name !== "write_file" ||
        args.path !== target.path ||
        typeof args.content !== "string"
      ) {
        continue;
      }

      const toolCallId = toolCall.id;
      const toolResult = toolCallId
        ? findToolResult(toolCallId, messages)
        : undefined;
      const isSelected =
        toolCallId === target.toolCallId &&
        (!target.messageId || message.id === target.messageId);
      if (isSelected && hasFailedWriteResult(toolResult)) {
        return undefined;
      }

      const shouldInclude =
        hasSuccessfulWriteResult(toolResult) ||
        (isSelected && toolResult === undefined);

      if (!shouldInclude) {
        continue;
      }

      if (args.append === true && hasDraft) {
        draft += args.content;
      } else {
        draft = args.content;
      }
      hasDraft = true;

      if (isSelected) {
        return draft;
      }
    }
  }

  return hasDraft ? draft : undefined;
}

export function getArtifactViewState({
  filepath,
  isSupportPreview,
  toolResult,
}: {
  filepath: string;
  isSupportPreview: boolean;
  toolResult?: string;
}): {
  canPreview: boolean;
  initialViewMode: ArtifactViewMode;
} {
  const isWriteArtifact = isWriteFileArtifact(filepath);
  const canPreview =
    isSupportPreview && (!isWriteArtifact || !hasFailedWriteResult(toolResult));
  return {
    canPreview,
    initialViewMode: canPreview ? "preview" : "code",
  };
}

export function appendHtmlPreviewBaseHref(
  content: string,
  url?: string,
  currentHref = globalThis.location?.href ?? "http://localhost/",
) {
  if (!url || /<base\s/i.exec(content)) {
    return content;
  }

  const baseHref = htmlBaseHref(url, currentHref);
  const baseElement = `<base href="${escapeHtmlAttribute(baseHref)}">`;
  if (/<head[^>]*>/i.exec(content)) {
    return content.replace(/<head([^>]*)>/i, `<head$1>${baseElement}`);
  }
  return `${baseElement}${content}`;
}

function htmlBaseHref(url: string, currentHref: string) {
  const baseUrl = new URL(url, currentHref);
  baseUrl.pathname = baseUrl.pathname.replace(/\/[^/]*$/, "/");
  baseUrl.search = "";
  baseUrl.hash = "";
  return baseUrl.toString();
}

function escapeHtmlAttribute(value: string) {
  return value.replaceAll("&", "&amp;").replaceAll('"', "&quot;");
}

export const HTML_PREVIEW_SCROLL_MESSAGE_SOURCE =
  "deerflow-artifact-preview-scroll";

export function createHtmlPreviewScrollKey(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `artifact-scroll:${(hash >>> 0).toString(36)}`;
}

function escapeJavaScriptString(value: string) {
  return JSON.stringify(value)
    .replace(/</g, "\\u003C")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function htmlScrollRestorationScript(messageKey: string) {
  return `<script data-deerflow-artifact-scroll-restoration>
(() => {
  const source = ${escapeJavaScriptString(HTML_PREVIEW_SCROLL_MESSAGE_SOURCE)};
  const key = ${escapeJavaScriptString(messageKey)};
  const post = (type, payload = {}) => {
    window.parent.postMessage({ source, key, type, ...payload }, "*");
  };
  const save = () => {
    post("save", {
      x: Math.round(window.scrollX || 0),
      y: Math.round(window.scrollY || 0),
    });
  };
  const restore = (x, y) => {
    if (Number.isFinite(x) && Number.isFinite(y)) {
      window.scrollTo(x, y);
    }
  };
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (
      !data ||
      data.source !== source ||
      data.key !== key ||
      data.type !== "restore"
    ) {
      return;
    }
    restore(data.x, data.y);
  });
  window.addEventListener("scroll", save, { passive: true });
  window.addEventListener("pagehide", save);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => post("restore-request"), { once: true });
  } else {
    post("restore-request");
  }
  window.addEventListener("load", () => post("restore-request"), { once: true });
})();
</script>`;
}

export function appendHtmlPreviewScrollRestoration(
  content: string,
  scrollKey = "default",
) {
  if (content.includes("data-deerflow-artifact-scroll-restoration")) {
    return content;
  }
  const script = htmlScrollRestorationScript(
    createHtmlPreviewScrollKey(scrollKey),
  );
  if (/<head(?:\s[^>]*)?>/i.test(content)) {
    return content.replace(
      /<head(?:\s[^>]*)?>/i,
      (headTag) => `${headTag}${script}`,
    );
  }
  if (/<\/body\s*>/i.test(content)) {
    return content.replace(/<\/body\s*>/i, `${script}</body>`);
  }
  return `${content}${script}`;
}
