"use client";

import { type ComponentProps } from "react";
import { Streamdown } from "streamdown";

import { installClipboardFallback } from "@/core/clipboard";

export type ClipboardSafeStreamdownProps = ComponentProps<typeof Streamdown>;

installClipboardFallback();

export function ClipboardSafeStreamdown(props: ClipboardSafeStreamdownProps) {
  return <Streamdown {...props} />;
}
