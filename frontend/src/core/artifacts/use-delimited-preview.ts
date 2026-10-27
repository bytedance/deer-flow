"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  DELIMITED_INPUT_LIMIT,
  DELIMITED_TIMEOUT_MS,
  type DelimitedPreviewInput,
  type DelimitedPreviewResponse,
  type DelimitedPreviewResult,
} from "./delimited-preview-types";

interface PreviewKey extends DelimitedPreviewInput {
  identity: string;
}

interface PreviewState {
  key: PreviewKey;
  attempt: number;
  status: "loading" | "ready" | "error";
  result?: DelimitedPreviewResult;
}

export function useDelimitedPreview({
  content,
  delimiter,
  truncated,
  active,
  identity,
}: DelimitedPreviewInput & { active: boolean; identity: string }) {
  const prefix = useMemo(() => {
    let end = Math.min(content.length, DELIMITED_INPUT_LIMIT);
    // Don't send half a Unicode character when the character budget cuts a pair.
    if (end < content.length) {
      const last = content.charCodeAt(end - 1);
      if (last >= 0xd800 && last <= 0xdbff) end--;
    }
    return content.slice(0, end);
  }, [content]);
  const isPrefix = truncated || prefix.length < content.length;
  const key = useMemo<PreviewKey>(
    () => ({ content: prefix, delimiter, truncated: isPrefix, identity }),
    [prefix, delimiter, isPrefix, identity],
  );
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PreviewState>();
  const settled = useRef<PreviewState | undefined>(undefined);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    if (!active) return;
    if (settled.current?.key === key && settled.current.attempt === attempt)
      return;
    let cancelled = false;
    let worker: Worker | undefined;
    const dispose = () => {
      clearTimeout(timer);
      worker?.terminate();
      worker = undefined;
    };
    const finish = (response: DelimitedPreviewResponse) => {
      if (cancelled) return;
      cancelled = true;
      dispose();
      const next: PreviewState =
        "result" in response
          ? { key, attempt, status: "ready", result: response.result }
          : { key, attempt, status: "error" };
      settled.current = next;
      setState(next);
    };
    setState({ key, attempt, status: "loading" });
    const timer = setTimeout(
      () => finish({ error: "timeout" }),
      DELIMITED_TIMEOUT_MS,
    );
    try {
      worker = new Worker(
        new URL("./delimited-preview.worker.ts", import.meta.url),
        {
          type: "module",
        },
      );
      worker.onmessage = (event: MessageEvent<DelimitedPreviewResponse>) =>
        finish(event.data);
      worker.onerror = () => finish({ error: "worker unavailable" });
      worker.onmessageerror = () => finish({ error: "invalid worker message" });
      worker.postMessage({ content: prefix, delimiter, truncated: isPrefix });
    } catch {
      finish({ error: "worker unavailable" });
    }
    return () => {
      cancelled = true;
      dispose();
    };
  }, [active, key, attempt, prefix, delimiter, isPrefix]);

  // Guard during render, before effects run, so another file never flashes here.
  const current =
    state?.key === key && state.attempt === attempt ? state : undefined;
  return {
    result: current?.result,
    status: current?.status ?? "loading",
    retry,
  };
}
