// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import {
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { useStickToBottom } from "use-stick-to-bottom";

import { ScrollArea } from "~/components/ui/scroll-area";
import { cn } from "~/lib/utils";

export interface ScrollContainerProps {
  className?: string;
  children?: ReactNode;
  scrollShadow?: boolean;
  scrollShadowColor?: string;
  autoScrollToBottom?: boolean;
  ref?: RefObject<ScrollContainerRef | null>;
}

export interface ScrollContainerRef {
  scrollToBottom(): void;
}

export function ScrollContainer({
  className,
  children,
  scrollShadow = true,
  scrollShadowColor = "var(--background)",
  autoScrollToBottom = false,
  ref,
}: ScrollContainerProps) {
  const { scrollRef, contentRef, scrollToBottom, isAtBottom } =
    useStickToBottom({ initial: "instant" });
  useImperativeHandle(ref, () => ({
    scrollToBottom() {
      if (isAtBottom) {
        scrollToBottom();
      }
    },
  }));

  const tempScrollRef = useRef<HTMLElement>(null);
  const tempContentRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!autoScrollToBottom) {
      tempScrollRef.current = scrollRef.current;
      tempContentRef.current = contentRef.current;
      scrollRef.current = null;
      contentRef.current = null;
    } else if (tempScrollRef.current && tempContentRef.current) {
      scrollRef.current = tempScrollRef.current;
      contentRef.current = tempContentRef.current;
    }
  }, [autoScrollToBottom, contentRef, scrollRef]);

  return (
    <div className={cn("relative", className)}>
      {scrollShadow && (
        <>
          <div
            className={cn(
              "absolute top-0 right-0 left-0 z-10 h-10 bg-gradient-to-t",
              `from-transparent to-[var(--scroll-shadow-color)]`,
            )}
            style={
              {
                "--scroll-shadow-color": scrollShadowColor,
              } as React.CSSProperties
            }
          ></div>
          <div
            className={cn(
              "absolute right-0 bottom-0 left-0 z-10 h-10 bg-gradient-to-b",
              `from-transparent to-[var(--scroll-shadow-color)]`,
            )}
            style={
              {
                "--scroll-shadow-color": scrollShadowColor,
              } as React.CSSProperties
            }
          ></div>
        </>
      )}
      <ScrollArea ref={scrollRef} className="h-full w-full">
        <div className="h-fit w-full" ref={contentRef}>
          {children}
        </div>
      </ScrollArea>
    </div>
  );
}
