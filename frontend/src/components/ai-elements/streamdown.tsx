"use client";

import { useMemo, type ComponentProps } from "react";
import { Streamdown } from "streamdown";

import { installClipboardFallback } from "@/core/clipboard";
import { capBlockquoteNesting } from "@/core/streamdown/preprocess";

export type ClipboardSafeStreamdownProps = ComponentProps<typeof Streamdown>;

// Only patch browser globals in client context; skip during SSR
if (typeof document !== "undefined") {
  installClipboardFallback();
}

export function ClipboardSafeStreamdown({
  children,
  ...props
}: ClipboardSafeStreamdownProps) {
  // Guard every Streamdown entry point against pathological blockquote
  // nesting, which overflows the call stack in marked's recursive lexer and
  // takes down the whole route.
  const safeChildren = useMemo(
    () =>
      typeof children === "string" ? capBlockquoteNesting(children) : children,
    [children],
  );
  return <Streamdown {...props}>{safeChildren}</Streamdown>;
}
