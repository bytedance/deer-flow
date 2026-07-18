"use client";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import {
  ReasoningContent,
  type ReasoningContentProps,
} from "@/components/ai-elements/reasoning";
import {
  ClipboardSafeStreamdown,
  type ClipboardSafeStreamdownProps,
} from "@/components/ai-elements/streamdown";

import {
  useSafeStreamdownChildren,
  useSafeStreamdownMarkdown,
} from "./safe-children";

export function SafeStreamdown({
  children,
  ...props
}: ClipboardSafeStreamdownProps) {
  const safeChildren = useSafeStreamdownChildren(children);

  return (
    <ClipboardSafeStreamdown {...props}>{safeChildren}</ClipboardSafeStreamdown>
  );
}

export function SafeMessageResponse({
  children,
  ...props
}: MessageResponseProps) {
  const safeChildren = useSafeStreamdownChildren(children);

  return <MessageResponse {...props}>{safeChildren}</MessageResponse>;
}

export function SafeReasoningContent({
  children,
  ...props
}: ReasoningContentProps) {
  const safeChildren = useSafeStreamdownMarkdown(children);

  return <ReasoningContent {...props}>{safeChildren}</ReasoningContent>;
}
