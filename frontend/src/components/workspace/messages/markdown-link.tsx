import type { AnchorHTMLAttributes } from "react";

import { resolveArtifactURL } from "@/core/artifacts/utils";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";

/**
 * Schemes we are willing to render as a navigable ``<a href=...>``.
 *
 * Anything else (``javascript:``, ``data:text/html``, ``vbscript:``,
 * ``file:``, …) is blocked because once it lands in a real anchor the
 * browser happily executes the payload in the chat surface where
 * sessionStorage / CSRF cookies are reachable. We accept only ``http`` /
 * ``https`` plus same-origin paths (which are governed by the artifact
 * branch below and ``resolveArtifactURL``) — relative ``/…`` URLs are
 * inherently safe and pass through ``URL.protocol === ""``.
 */
const SAFE_HREF_PROTOCOLS = ["http:", "https:"] as const;

export function isSafeHref(href: string | undefined): boolean {
  if (typeof href !== "string" || href.length === 0) {
    return false;
  }
  // Allow relative same-origin paths (no protocol — e.g. "/workspace/foo").
  if (href.startsWith("/") && !href.startsWith("//")) {
    return true;
  }
  // Allow same-document anchors (e.g. "#section").
  if (href.startsWith("#")) {
    return true;
  }
  try {
    const parsed = new URL(href);
    return (SAFE_HREF_PROTOCOLS as ReadonlyArray<string>).includes(
      parsed.protocol,
    );
  } catch {
    return false;
  }
}

function isExternalUrl(href: string | undefined): boolean {
  if (typeof href !== "string") {
    return false;
  }
  return /^https?:\/\//.test(href);
}

/**
 * Builds the `a` renderer shared by message content and generic markdown.
 * Passing a `threadId` also resolves `/mnt/` artifact links; without it those
 * links fall through to the default external-link handling.
 */
export function createMarkdownLinkComponent(threadId?: string) {
  return function MarkdownLink({
    href,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement>) {
    if (typeof props.children === "string") {
      const match = /^citation:(.+)$/.exec(props.children);
      if (match) {
        const [, text] = match;
        return (
          <CitationLink {...props} href={href}>
            {text}
          </CitationLink>
        );
      }
    }
    // Reject unsafe schemes up front so a prompt-injected / pasted href can
    // never reach the rendered anchor. Keep the visible label so the user
    // can still see what the link claimed to point at.
    if (href !== undefined && !isSafeHref(href)) {
      const { className, children, ...rest } = props;
      return (
        <span
          {...rest}
          className={cn(
            "text-muted-foreground cursor-not-allowed underline decoration-dotted underline-offset-2",
            className,
          )}
          aria-label="Unsafe link omitted"
          title={`Unsafe link scheme in ${href}`}
        >
          {children}
        </span>
      );
    }
    if (threadId && href?.startsWith("/mnt/")) {
      return (
        <a
          {...props}
          href={resolveArtifactURL(href, threadId)}
          target="_blank"
          rel="noopener noreferrer"
        />
      );
    }
    const { className, target, rel, ...rest } = props;
    const external = isExternalUrl(href);
    return (
      <a
        {...rest}
        href={href}
        className={cn(
          "text-primary decoration-primary/30 hover:decoration-primary/60 underline underline-offset-2 transition-colors",
          className,
        )}
        target={target ?? (external ? "_blank" : undefined)}
        rel={rel ?? (external ? "noopener noreferrer" : undefined)}
      />
    );
  };
}
