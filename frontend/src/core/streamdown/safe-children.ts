import { useMemo } from "react";
import type { ComponentProps } from "react";
import { type Streamdown } from "streamdown";

import {
  capMarkdownNesting,
  normalizeStreamdownMathMarkdown,
} from "./preprocess";

type StreamdownChildren = ComponentProps<typeof Streamdown>["children"];

export function getSafeStreamdownMarkdown(markdown: string): string {
  return normalizeStreamdownMathMarkdown(capMarkdownNesting(markdown));
}

export function getSafeStreamdownChildren(
  children: StreamdownChildren,
): StreamdownChildren {
  if (typeof children !== "string") {
    return children;
  }

  return getSafeStreamdownMarkdown(children);
}

export function useSafeStreamdownChildren(
  children: StreamdownChildren,
): StreamdownChildren {
  return useMemo(() => getSafeStreamdownChildren(children), [children]);
}

export function useSafeStreamdownMarkdown(markdown: string): string {
  return useMemo(() => getSafeStreamdownMarkdown(markdown), [markdown]);
}
