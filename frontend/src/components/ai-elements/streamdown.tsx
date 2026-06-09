"use client";

import { type ComponentProps } from "react";
import { Streamdown } from "streamdown";

import { installClipboardFallback } from "@/core/clipboard";

export type ClipboardSafeStreamdownProps = ComponentProps<typeof Streamdown>;

// Only patch browser globals in client context; skip during SSR
if (typeof document !== "undefined") {
  installClipboardFallback();
}

export function ClipboardSafeStreamdown(props: ClipboardSafeStreamdownProps) {
  return <Streamdown {...props} />;
}
