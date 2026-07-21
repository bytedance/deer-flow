import type { AnchorHTMLAttributes } from "react";

import { resolveMarkdownArtifactURL } from "@/core/artifacts/utils";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";

/**
 * Schemes we are willing to render as a navigable ``<a href=...>``.
 *
 * Anything else (``javascript:``, ``data:text/html``, ``vbscript:``,
 * ``file:``, …) is blocked because once it lands in a real anchor the
 * browser happily executes the payload in the chat surface where
 * sessionStorage / CSRF cookies are reachable. We accept ``http(s)``
 * plus the non-executing ``mailto:`` / ``tel:`` schemes; same-origin
 * absolute paths (``/…``), scheme-less relative references (``report.md``,
 * ``./…``, ``../…``), and in-document anchors (``#…``) are also allowed
 * — they all resolve under the current HTTP(S) origin.
 */
const SAFE_HREF_PROTOCOLS = ["http:", "https:", "mailto:", "tel:"] as const;

export function isSafeHref(href: string | undefined): boolean {
  if (typeof href !== "string" || href.length === 0) {
    return false;
  }
  // Same-document anchors (e.g. "#section").
  if (href.startsWith("#")) {
    return true;
  }
  // Protocol-relative URLs (//evil.com/path) would inherit the current
  // page's scheme and navigate to an unknown host. Also reject
  // backslash-normalised variants (\\evil.com → //evil.com) because
  // browsers treat backslash as a path separator in URLs.
  if (/^(\/\/|\\\\)/.test(href)) {
    return false;
  }
  // Parse the href so we can inspect its scheme. Items without an explicit
  // protocol (report.md, ./report.md, ../assets/chart.png, /workspace/foo)
  // resolve relative to the dummy HTTPS base, producing an https: URL.
  // Explicitly-schemed URLs (https://…, mailto:, javascript:, data:, …)
  // keep their native scheme, which we then check against the allowlist.
  try {
    const parsed = new URL(href, "https://dummy.example/");
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
    // Reject unsafe schemes up front so a prompt-injected / pasted href can
    // never reach the rendered anchor — including through the citation
    // branch (which renders <a href={href}> directly). Check before the
    // citation block so prompt-injected [citation:x](javascript:...) is
    // blocked. Keep the visible label so the user can still see what the
    // link claimed to point at.
    if (href !== undefined && !isSafeHref(href)) {
      // Intentionally no {...props} spread: react-markdown props like `node`
      // (and anchor-only attributes such as target/rel) are not valid on a
      // <span> and would trigger React DOM warnings.
      const { className, children } = props;
      return (
        <span
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
    // Safe-href check passed — citation links now route through CitationLink.
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
    if (threadId && href?.startsWith("/mnt/")) {
      return (
        <a
          {...props}
          href={resolveMarkdownArtifactURL(href, threadId)}
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
