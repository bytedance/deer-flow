import type { AnchorHTMLAttributes } from "react";

import { knowledgeSourceId } from "@/core/knowledge/sources";
import { cn } from "@/lib/utils";

import { isSafeHref, UnsafeLink } from "../messages/markdown-link";

import { CitationLink, extractReactNodeText } from "./citation-link";

function isExternalUrl(href: string | undefined): boolean {
  return !!href && /^https?:\/\//.test(href);
}

/** Knowledge destinations and citation-prefixed links use the source renderer. */
export function ArtifactLink(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
  // Reject unsafe schemes so prompt-injected [label](javascript:...) in a .md
  // artifact preview cannot execute in the main document, matching the guard in
  // createMarkdownLinkComponent (markdown-link.tsx).
  if (props.href !== undefined && !isSafeHref(props.href)) {
    // Intentionally no {...props} spread: anchor-only attributes (href,
    // target, rel) are not valid on a <span> and would leak the unsafe URL
    // into the DOM / trigger React DOM warnings.
    const { className, children } = props;
    return (
      <UnsafeLink href={props.href} className={className}>
        {children}
      </UnsafeLink>
    );
  }
  if (knowledgeSourceId(props.href)) {
    return <CitationLink {...props} />;
  }
  const childrenText = extractReactNodeText(props.children);
  if (childrenText !== null) {
    const match = /^citation:(.+)$/.exec(childrenText);
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
