"use client";

import {
  createContext,
  type ComponentProps,
  isValidElement,
  type ReactNode,
  useContext,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { type ClipboardSafeStreamdownProps } from "@/components/ai-elements/streamdown";
import {
  preprocessStreamdownMarkdown,
  streamdownPluginsWithoutRawHtml,
} from "@/core/streamdown";
import { SafeMessageResponse } from "@/core/streamdown/components";
import { cn } from "@/lib/utils";

import { createMarkdownLinkComponent } from "./markdown-link";

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins?: ClipboardSafeStreamdownProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: ClipboardSafeStreamdownProps["remarkPlugins"];
  components?: ClipboardSafeStreamdownProps["components"];
};

type StreamingCodeProps = ComponentProps<"code"> & {
  node?: unknown;
  children?: ReactNode;
};

const SMOOTH_REVEAL_MIN_DELTA = 80;
const SMOOTH_REVEAL_MIN_CHARS_PER_FRAME = 8;
const SMOOTH_REVEAL_DURATION_MS = 300;

const StreamingCodeBlockContext = createContext(false);

function useSmoothStreamingContent(content: string, isLoading: boolean) {
  const initialContent =
    isLoading && content.length >= SMOOTH_REVEAL_MIN_DELTA ? "" : content;
  const [displayContent, setDisplayContent] = useState(initialContent);
  const displayContentRef = useRef(initialContent);
  const targetContentRef = useRef(content);
  const sawLoadingRef = useRef(isLoading);

  useEffect(() => {
    if (isLoading) {
      sawLoadingRef.current = true;
    }
  }, [isLoading]);

  useEffect(() => {
    targetContentRef.current = content;

    const current = displayContentRef.current;
    const delta = content.length - current.length;
    const shouldSmoothReveal =
      delta >= SMOOTH_REVEAL_MIN_DELTA &&
      content.startsWith(current) &&
      (isLoading || sawLoadingRef.current);

    if (!shouldSmoothReveal) {
      if (current !== content) {
        displayContentRef.current = content;
        setDisplayContent(content);
      }
      if (!isLoading) {
        sawLoadingRef.current = false;
      }
      return;
    }

    let cancelled = false;
    let frame: number | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let generation = 0;
    const startedAt = performance.now();
    const startLength = current.length;

    const tick = (now: number, scheduledGeneration: number) => {
      if (cancelled || scheduledGeneration !== generation) {
        return;
      }
      generation += 1;
      if (frame !== null) {
        cancelAnimationFrame(frame);
        frame = null;
      }
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }

      const target = targetContentRef.current;
      const latest = displayContentRef.current;
      if (!target.startsWith(latest) || latest.length >= target.length) {
        if (!isLoading) {
          sawLoadingRef.current = false;
        }
        return;
      }

      const progress = Math.min(
        1,
        (now - startedAt) / SMOOTH_REVEAL_DURATION_MS,
      );
      const elapsedLength = startLength + Math.ceil(delta * progress);
      const nextLength = Math.max(
        latest.length + SMOOTH_REVEAL_MIN_CHARS_PER_FRAME,
        elapsedLength,
      );
      const next = target.slice(0, nextLength);
      displayContentRef.current = next;
      setDisplayContent(next);

      if (next.length < target.length) {
        scheduleTick();
      } else if (!isLoading) {
        sawLoadingRef.current = false;
      }
    };

    const scheduleTick = () => {
      const scheduledGeneration = ++generation;
      frame = requestAnimationFrame((now) => tick(now, scheduledGeneration));
      timer = setTimeout(
        () => tick(performance.now(), scheduledGeneration),
        50,
      );
    };

    scheduleTick();
    return () => {
      cancelled = true;
      generation += 1;
      if (frame !== null) {
        cancelAnimationFrame(frame);
      }
      if (timer !== null) {
        clearTimeout(timer);
      }
    };
  }, [content, isLoading]);

  return {
    content: displayContent,
    isRevealing: displayContent !== content,
  };
}

function StreamingPre({ children }: ComponentProps<"pre">) {
  const childClassName = isValidElement<{ className?: string }>(children)
    ? children.props.className
    : undefined;
  const language =
    /(?:^|\s)language-([^\s]+)/.exec(childClassName ?? "")?.[1] ?? "";

  return (
    <div
      className="my-4 w-full overflow-hidden rounded-xl border"
      data-language={language}
      data-streaming-code-block="true"
    >
      {language && (
        <div className="bg-muted/80 text-muted-foreground p-3 text-xs">
          <span className="ml-1 font-mono lowercase">{language}</span>
        </div>
      )}
      <pre className="bg-muted/40 overflow-x-auto border-t p-4 font-mono text-xs">
        <StreamingCodeBlockContext.Provider value={true}>
          {children}
        </StreamingCodeBlockContext.Provider>
      </pre>
    </div>
  );
}

function StreamingCode({
  children,
  className,
  node: _node,
  ...props
}: StreamingCodeProps) {
  const isBlock = useContext(StreamingCodeBlockContext);

  if (!isBlock) {
    return (
      <code
        {...props}
        className={cn(
          "bg-muted rounded px-1.5 py-0.5 font-mono text-sm",
          className,
        )}
        data-streaming-inline-code="true"
      >
        {children}
      </code>
    );
  }

  return (
    <code {...props} className={className}>
      {children}
    </code>
  );
}

/** Renders markdown content. */
export function MarkdownContent({
  content,
  isLoading,
  rehypePlugins,
  className,
  remarkPlugins = streamdownPluginsWithoutRawHtml.remarkPlugins,
  components: componentsFromProps,
}: MarkdownContentProps) {
  const deferredContent = useDeferredValue(content);
  const targetContent = isLoading ? deferredContent : content;
  const { content: displayContent, isRevealing } = useSmoothStreamingContent(
    targetContent,
    isLoading,
  );
  const isStreamingRender = isLoading || isRevealing;
  const normalizedContent = useMemo(
    () => preprocessStreamdownMarkdown(displayContent),
    [displayContent],
  );
  const effectiveRehypePlugins = useMemo(() => {
    const base = streamdownPluginsWithoutRawHtml.rehypePlugins ?? [];
    const extra = rehypePlugins ?? [];
    return [...base, ...extra] as ClipboardSafeStreamdownProps["rehypePlugins"];
  }, [rehypePlugins]);
  const components = useMemo(() => {
    const baseComponents = {
      a: createMarkdownLinkComponent(),
      ...componentsFromProps,
    };
    if (!isStreamingRender) {
      return baseComponents;
    }
    return {
      ...baseComponents,
      code: componentsFromProps?.code ?? StreamingCode,
      pre: componentsFromProps?.pre ?? StreamingPre,
    };
  }, [componentsFromProps, isStreamingRender]);

  if (!displayContent) return null;

  return (
    <SafeMessageResponse
      className={className}
      remarkPlugins={remarkPlugins}
      rehypePlugins={effectiveRehypePlugins}
      components={components}
      parseIncompleteMarkdown={isStreamingRender}
    >
      {normalizedContent}
    </SafeMessageResponse>
  );
}
