import { ExternalLinkIcon } from "lucide-react";
import { isValidElement, type ComponentProps, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { cn } from "@/lib/utils";

/** Extract visible text from renderer-provided ReactNode children. */
export function extractReactNodeText(node: ReactNode): string | null {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    const text = node
      .map(extractReactNodeText)
      .filter((value): value is string => value !== null)
      .join("");
    return text || null;
  }
  if (isValidElement(node)) {
    const children = (node.props as { children?: ReactNode }).children;
    return children === undefined ? null : extractReactNodeText(children);
  }
  return null;
}

export function CitationLink({
  href,
  children,
  ...props
}: ComponentProps<"a">) {
  const domain = extractDomain(href ?? "");

  // Priority: children > domain
  const childrenText =
    extractReactNodeText(children)?.replace(/^citation:\s*/i, "") ?? null;
  const isGenericText = childrenText === "Source" || childrenText === "来源";
  const displayText = (!isGenericText && childrenText) ?? domain;

  return (
    <HoverCard closeDelay={0} openDelay={0}>
      <HoverCardTrigger asChild>
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center"
          onClick={(e) => e.stopPropagation()}
          {...props}
        >
          <Badge
            variant="secondary"
            className="hover:bg-secondary/80 mx-0.5 cursor-pointer gap-1 rounded-full px-2 py-0.5 text-xs font-normal"
          >
            {displayText}
            <ExternalLinkIcon className="size-3" />
          </Badge>
        </a>
      </HoverCardTrigger>
      <HoverCardContent className={cn("relative w-80 p-0", props.className)}>
        <div className="p-3">
          <div className="space-y-1">
            {displayText && (
              <h4 className="truncate text-sm leading-tight font-medium">
                {displayText}
              </h4>
            )}
            {href && (
              <p className="text-muted-foreground truncate text-xs break-all">
                {href}
              </p>
            )}
          </div>
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary mt-2 inline-flex items-center gap-1 text-xs hover:underline"
          >
            Visit source
            <ExternalLinkIcon className="size-3" />
          </a>
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return url;
  }
}
