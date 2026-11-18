import { type StreamdownComponentOverrides } from "@/core/streamdown/components";

import {
  createMarkdownLinkComponent,
  isSafeHref,
} from "../messages/markdown-link";

const MarkdownLink = createMarkdownLinkComponent();

// Only SKILL.md is captured. Package-relative links and images have no resource
// backing in this snapshot, so never resolve them against the current chat URL.
export const snapshotMarkdownComponents: StreamdownComponentOverrides = {
  a: ({ href, children, className, title }) => {
    if (href && /^(https?:\/\/|mailto:|tel:)/i.test(href) && isSafeHref(href)) {
      return (
        <MarkdownLink href={href} className={className} title={title}>
          {children}
        </MarkdownLink>
      );
    }
    return (
      <span
        className="text-muted-foreground decoration-muted-foreground/50 underline decoration-dotted underline-offset-2"
        title={href}
      >
        {children}
      </span>
    );
  },
  img: ({ src, alt, title }) => {
    if (
      typeof src === "string" &&
      /^https?:\/\//i.test(src) &&
      isSafeHref(src)
    ) {
      // Preserve the shared renderer's remote image behavior without fetching
      // unresolved package paths or requiring a new skill-resource endpoint.
      return (
        <img
          src={src}
          alt={alt ?? ""}
          title={title}
          loading="lazy"
          className="max-w-full"
        />
      );
    }
    return (
      <span
        className="text-muted-foreground text-sm"
        title={typeof src === "string" ? src : undefined}
      >
        {alt?.trim() ? alt : typeof src === "string" ? src : ""}
      </span>
    );
  },
};
