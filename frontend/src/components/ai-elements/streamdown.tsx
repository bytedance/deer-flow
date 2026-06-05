"use client";

import { useEffect, type ComponentProps } from "react";
import { Streamdown } from "streamdown";

import { installClipboardFallback } from "@/core/clipboard";

export type ClipboardSafeStreamdownProps = ComponentProps<typeof Streamdown>;

export function ClipboardSafeStreamdown(props: ClipboardSafeStreamdownProps) {
  useEffect(() => {
    installClipboardFallback();
  }, []);

  return <Streamdown {...props} />;
}
