import type { WorkspaceLifetime } from "@/core/workspaces/session";

import { planHTMLModule } from "./html-module-plan";
import { HTML_ARTIFACT_CHILD } from "./html-resource-child";
import { planHTMLDocument, planHTMLStylesheet } from "./html-resource-plan";
import { createHTMLArtifactResourceReader } from "./html-resource-reader";
import {
  appendHtmlPreviewScrollRestoration,
  HTML_PREVIEW_SCROLL_MESSAGE_SOURCE,
} from "./preview";

/** A single opaque document gets one private, retiring, read-only byte port. */
export function createHTMLArtifactResourceSession({
  content,
  sourceURL,
  lifetime,
  iframe,
  isCurrent,
  position,
}: {
  content: string;
  sourceURL: string;
  lifetime: WorkspaceLifetime;
  iframe: () => HTMLIFrameElement | null;
  isCurrent: () => boolean;
  position: { current: { x: number; y: number } };
}) {
  const reader = createHTMLArtifactResourceReader({ sourceURL, lifetime });
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(24)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  const plan = planHTMLDocument(
    appendHtmlPreviewScrollRestoration(content, nonce, nonce),
    reader,
    nonce,
  );
  const reads = new Map<number, AbortController>();
  let closed = false;
  let connected = false;
  let port: MessagePort | undefined;
  const current = () =>
    !closed && isCurrent() && !lifetime.scope.signal.aborted;
  const onReady = (event: MessageEvent) => {
    if (!current() || event.source !== iframe()?.contentWindow) return;
    const data = event.data;
    if (
      data?.source === HTML_PREVIEW_SCROLL_MESSAGE_SOURCE &&
      data.key === nonce
    ) {
      if (
        data.type === "save" &&
        Number.isFinite(data.x) &&
        Number.isFinite(data.y)
      )
        position.current = { x: data.x, y: data.y };
      else if (data.type === "restore-request")
        iframe()?.contentWindow?.postMessage(
          {
            source: HTML_PREVIEW_SCROLL_MESSAGE_SOURCE,
            key: nonce,
            type: "restore",
            ...position.current,
          },
          "*",
        );
      return;
    }
    if (
      connected ||
      data?.type !== "deerflow-html-ready" ||
      data.nonce !== nonce
    )
      return;
    connected = true;
    const channel = new MessageChannel();
    port = channel.port1;
    port.onmessage = (message: MessageEvent) => {
      const data: unknown = message.data;
      if (!current() || !data || typeof data !== "object" || !("type" in data))
        return;
      if (data.type === "close") {
        dispose();
        return;
      }
      if (
        !("id" in data) ||
        typeof data.id !== "number" ||
        !Number.isSafeInteger(data.id) ||
        data.id < 1
      )
        return;
      const id = data.id;
      if (data.type === "cancel") {
        reads.get(id)?.abort();
        return;
      }
      if (
        data.type !== "read" ||
        reads.has(id) ||
        !("reference" in data) ||
        typeof data.reference !== "string" ||
        !("baseURL" in data) ||
        typeof data.baseURL !== "string" ||
        !("kind" in data) ||
        (data.kind !== "css" && data.kind !== "asset" && data.kind !== "module")
      )
        return;
      const controller = new AbortController();
      reads.set(id, controller);
      const kind = data.kind;
      void reader
        .read(data.reference, {
          baseURL: data.baseURL,
          signal: controller.signal,
        })
        .then((resource) => {
          if (!current() || controller.signal.aborted) return;
          const css =
            kind === "css"
              ? planHTMLStylesheet(new TextDecoder().decode(resource.bytes))
              : undefined;
          const module = kind === "module" ? planHTMLModule(new TextDecoder().decode(resource.bytes)) : undefined;
          port?.postMessage({ type: "resource", id, ...resource, css,module }, [
            resource.bytes,
          ]);
        })
        .catch(() => {
          if (current() && !controller.signal.aborted)
            port?.postMessage({ type: "error", id });
        })
        .finally(() => {
          reads.delete(id);
        });
    };
    channel.port1.start();
    iframe()?.contentWindow?.postMessage(
      { type: "deerflow-html-connect", nonce, plan },
      "*",
      [channel.port2],
    );
  };
  function dispose() {
    if (closed) return;
    closed = true;
    window.removeEventListener("message", onReady);
    lifetime.scope.signal.removeEventListener("abort", dispose);
    for (const controller of reads.values()) controller.abort();
    reads.clear();
    reader.dispose();
    port?.postMessage({ type: "dispose" });
    port?.close();
    URL.revokeObjectURL(url);
  }
  const script = HTML_ARTIFACT_CHILD.replace(
    "__DEERFLOW_NONCE__",
    JSON.stringify(nonce),
  );
  const url = URL.createObjectURL(
    new Blob([`<!doctype html><script>${script}</script>`], {
      type: "text/html;charset=utf-8",
    }),
  );
  window.addEventListener("message", onReady);
  lifetime.scope.signal.addEventListener("abort", dispose, { once: true });
  return { url, dispose };
}
