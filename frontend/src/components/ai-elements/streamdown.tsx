"use client";

import { Component, useMemo, type ComponentProps, type ReactNode } from "react";
import { Streamdown } from "streamdown";

import { installClipboardFallback } from "@/core/clipboard";
import { capBlockquoteNesting } from "@/core/streamdown/preprocess";

export type ClipboardSafeStreamdownProps = ComponentProps<typeof Streamdown>;

// Only patch browser globals in client context; skip during SSR
if (typeof document !== "undefined") {
  installClipboardFallback();
}

// marked (used by Streamdown to split content into blocks) has mutually
// recursive tokenizers — blockquote/list nesting a couple thousand levels
// deep overflows the call stack during render and would otherwise take down
// the whole route. When rendering a message throws, fall back to showing
// that message as plain pre-formatted text instead.
class StreamdownFallbackBoundary extends Component<
  { raw: ClipboardSafeStreamdownProps["children"]; children: ReactNode },
  { errored: boolean; prevRaw: ClipboardSafeStreamdownProps["children"] }
> {
  state = { errored: false, prevRaw: this.props.raw };

  static getDerivedStateFromError() {
    return { errored: true };
  }

  static getDerivedStateFromProps(
    props: { raw: ClipboardSafeStreamdownProps["children"] },
    state: {
      errored: boolean;
      prevRaw: ClipboardSafeStreamdownProps["children"];
    },
  ) {
    // Retry rendering when the content changes (e.g. the next streaming chunk).
    if (props.raw !== state.prevRaw) {
      return { errored: false, prevRaw: props.raw };
    }
    return null;
  }

  render() {
    if (this.state.errored) {
      return (
        <div className="break-words whitespace-pre-wrap">
          {typeof this.props.raw === "string" ? this.props.raw : null}
        </div>
      );
    }
    return this.props.children;
  }
}

export function ClipboardSafeStreamdown({
  children,
  ...props
}: ClipboardSafeStreamdownProps) {
  // Fast path for the dominant pathological input (pure ">" chains) so the
  // error boundary below rarely has to absorb a full stack overflow.
  const safeChildren = useMemo(
    () =>
      typeof children === "string" ? capBlockquoteNesting(children) : children,
    [children],
  );
  return (
    <StreamdownFallbackBoundary raw={children}>
      <Streamdown {...props}>{safeChildren}</Streamdown>
    </StreamdownFallbackBoundary>
  );
}
