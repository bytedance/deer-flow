"use client";

import { useLayoutEffect, type ComponentProps } from "react";
import { Streamdown } from "streamdown";

import { installClipboardFallback } from "@/core/clipboard";

export type ClipboardSafeStreamdownProps = ComponentProps<typeof Streamdown>;

export function ClipboardSafeStreamdown(props: ClipboardSafeStreamdownProps) {
  useLayoutEffect(() => {
    installClipboardFallback();
  }, []);

  return <Streamdown {...props} />;
}
