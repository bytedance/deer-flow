"use client";

import type { ComponentType, JSX } from "react";
import type { Components, ExtraProps } from "streamdown";

import {
  ReasoningContent,
  type ReasoningContentProps,
} from "@/components/ai-elements/reasoning";
import {
  ClipboardSafeStreamdown,
  type ClipboardSafeStreamdownProps,
} from "@/components/ai-elements/streamdown";
import { cn } from "@/lib/utils";

import { streamdownRenderingPlugins } from "./plugins";
import {
  useSafeStreamdownChildren,
  useSafeStreamdownMarkdown,
} from "./safe-children";

export type StreamdownComponentOverrides = {
  [Key in keyof JSX.IntrinsicElements]?:
    | ComponentType<JSX.IntrinsicElements[Key] & ExtraProps>
    | keyof JSX.IntrinsicElements;
} & {
  inlineCode?: ComponentType<JSX.IntrinsicElements["code"] & ExtraProps>;
};

/**
 * Adapts normal intrinsic-element overrides to Streamdown's component map.
 *
 * Streamdown 2.5's public `Components` type combines those overrides with a
 * catch-all index signature whose generic props reject correctly typed React
 * components. The runtime contract still accepts this standard component map,
 * so keep the compatibility cast at this boundary instead of every caller.
 */
export function toStreamdownComponents(
  components: StreamdownComponentOverrides,
): Components {
  return components as unknown as Components;
}

export function SafeStreamdown({
  children,
  plugins = streamdownRenderingPlugins,
  ...props
}: ClipboardSafeStreamdownProps) {
  const safeChildren = useSafeStreamdownChildren(children);

  return (
    <ClipboardSafeStreamdown plugins={plugins} {...props}>
      {safeChildren}
    </ClipboardSafeStreamdown>
  );
}

export function SafeMessageResponse({
  children,
  className,
  plugins = streamdownRenderingPlugins,
  ...props
}: ClipboardSafeStreamdownProps) {
  const safeChildren = useSafeStreamdownChildren(children);

  // Keep this wrapper outside the registry-generated MessageResponse component.
  // That component memoizes only by children, while Streamdown's animation
  // lifecycle also needs isAnimating/animated prop changes to render.
  return (
    <ClipboardSafeStreamdown
      className={cn(
        "size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
        className,
      )}
      plugins={plugins}
      {...props}
    >
      {safeChildren}
    </ClipboardSafeStreamdown>
  );
}

export function SafeReasoningContent({
  children,
  ...props
}: ReasoningContentProps) {
  const safeChildren = useSafeStreamdownMarkdown(children);

  return <ReasoningContent {...props}>{safeChildren}</ReasoningContent>;
}
