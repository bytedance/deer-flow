// Main-thread client for the Shiki highlight worker.
//
// A single worker instance is shared by every CodeBlock in the page — Shiki's
// internal singleton highlighter caches grammar data, so reusing one worker
// avoids loading the bundle more than once. Requests are identified by a
// monotonically increasing id; callers receive a Promise that resolves (or
// rejects) when the worker sends back a matching response.
//
// Cancellation / staleness is the caller's responsibility: when a CodeBlock
// prop changes rapidly (for instance, during streaming), the caller starts a
// new request and discards the previous promise's result. The worker still
// finishes the in-flight job but the UI ignores it — see
// `code-block.tsx` for the generation-counter pattern.

import type { BundledLanguage } from "shiki";

import type { HighlightRequest, HighlightResponse } from "./worker";

type PendingEntry = {
  resolve: (result: [string, string]) => void;
  reject: (error: Error) => void;
};

let workerInstance: Worker | null = null;
let nextRequestId = 0;
const pending = new Map<number, PendingEntry>();

function getWorker(): Worker | null {
  if (typeof window === "undefined" || typeof Worker === "undefined") {
    // SSR / environments without Worker support — caller falls back to
    // skipping syntax highlighting.
    return null;
  }
  if (workerInstance !== null) {
    return workerInstance;
  }

  const worker = new Worker(new URL("./worker.ts", import.meta.url), {
    type: "module",
  });

  worker.addEventListener("message", (event: MessageEvent<HighlightResponse>) => {
    const { id, light, dark, error } = event.data;
    const entry = pending.get(id);
    if (!entry) {
      return;
    }
    pending.delete(id);
    if (error !== undefined) {
      entry.reject(new Error(error));
      return;
    }
    if (typeof light !== "string" || typeof dark !== "string") {
      entry.reject(new Error("Shiki worker returned malformed response"));
      return;
    }
    entry.resolve([light, dark]);
  });

  worker.addEventListener("error", (event) => {
    // A fatal worker error invalidates every in-flight request. Reject them
    // so callers can surface a readable error instead of hanging.
    const message = event.message || "Shiki worker crashed";
    for (const entry of pending.values()) {
      entry.reject(new Error(message));
    }
    pending.clear();
    // Drop the broken instance; next call will lazily spawn a fresh one.
    workerInstance = null;
  });

  workerInstance = worker;
  return worker;
}

/**
 * Highlight a code snippet in the shared Shiki worker.
 *
 * Resolves to ``[lightHtml, darkHtml]`` on success. Rejects if the worker
 * crashes, if the language bundle fails to load, or if the environment
 * lacks Worker support (e.g. during SSR).
 */
export function highlightInWorker(
  code: string,
  language: BundledLanguage,
  showLineNumbers: boolean,
): Promise<[string, string]> {
  const worker = getWorker();
  if (worker === null) {
    return Promise.reject(new Error("Web Worker not available"));
  }

  const id = nextRequestId++;
  return new Promise<[string, string]>((resolve, reject) => {
    pending.set(id, { resolve, reject });
    const request: HighlightRequest = {
      id,
      code,
      lang: language,
      showLineNumbers,
    };
    worker.postMessage(request);
  });
}
