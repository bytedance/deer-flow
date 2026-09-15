"use client";

import { Component, type ComponentProps, type ReactNode } from "react";
import { Streamdown } from "streamdown";

import { stripLeakedSystemTags } from "@/core/streamdown/preprocess";
import { installClipboardFallback } from "@/core/clipboard";

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
  // Strip leaked system-internal tags (<memory>, <system-reminder>, etc.)
  // that would cause React to log "unrecognized tag" console errors when
  // the markdown renderer passes them through as raw HTML.
  const sanitizedChildren =
    typeof children === "string" ? stripLeakedSystemTags(children) : children;

  return (
    <StreamdownFallbackBoundary raw={sanitizedChildren}>
      <Streamdown {...props}>{sanitizedChildren}</Streamdown>
    </StreamdownFallbackBoundary>
  );
}
