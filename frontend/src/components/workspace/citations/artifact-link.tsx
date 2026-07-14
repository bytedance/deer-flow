import type { AnchorHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

import { isSafeHref } from "../messages/markdown-link";

import { CitationLink } from "./citation-link";

function isExternalUrl(href: string | undefined): boolean {
  return !!href && /^https?:\/\//.test(href);
}

/** Link renderer for artifact markdown: citation: prefix → CitationLink, otherwise underlined text. */
export function ArtifactLink(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
  // Reject unsafe schemes so prompt-injected [label](javascript:...) in a .md
  // artifact preview cannot execute in the main document, matching the guard in
  // createMarkdownLinkComponent (markdown-link.tsx).
  if (props.href !== undefined && !isSafeHref(props.href)) {
    const { className, children, target, rel, ...rest } = props;
    return (
      <span
        {...rest}
        className={cn(
          "text-muted-foreground cursor-not-allowed underline decoration-dotted underline-offset-2",
          className,
        )}
        aria-label="Unsafe link omitted"
        title={`Unsafe link scheme in ${props.href}`}
      >
        {children}
      </span>
    );
  }
  if (typeof props.children === "string") {
    const match = /^citation:(.+)$/.exec(props.children);
    if (match) {
      const [, text] = match;
      return <CitationLink {...props}>{text}</CitationLink>;
    }
  }
  const { className, target, rel, ...rest } = props;
  const external = isExternalUrl(props.href);
  return (
    <a
      {...rest}
      className={cn(
        "text-primary decoration-primary/30 hover:decoration-primary/60 underline underline-offset-2 transition-colors",
        className,
      )}
      target={target ?? (external ? "_blank" : undefined)}
      rel={rel ?? (external ? "noopener noreferrer" : undefined)}
    />
  );
}
