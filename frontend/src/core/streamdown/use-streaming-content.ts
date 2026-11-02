"use client";

import { useEffect, useRef, useState } from "react";

const STREAMING_RENDER_INTERVAL_MS = 50;

/** Bound Markdown work without waiting for a continuous stream to go idle. */
export function useStreamingContent(content: string, isStreaming: boolean) {
  const [displayContent, setDisplayContent] = useState(content);
  const pendingContent = useRef(content);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    pendingContent.current = content;

    if (!isStreaming || !content.startsWith(displayContent)) {
      if (timer.current !== null) {
        clearTimeout(timer.current);
        timer.current = null;
      }
      setDisplayContent(content);
      return;
    }

    if (content === displayContent || timer.current !== null) return;

    timer.current = setTimeout(() => {
      timer.current = null;
      setDisplayContent(pendingContent.current);
    }, STREAMING_RENDER_INTERVAL_MS);
  }, [content, displayContent, isStreaming]);

  useEffect(
    () => () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
        timer.current = null;
      }
    },
    [],
  );

  // Completion and replacement must not wait for an outstanding render timer.
  return !isStreaming || !content.startsWith(displayContent)
    ? content
    : displayContent;
}
