import { ExternalLinkIcon } from "lucide-react";
import type { ComponentProps } from "react";

import { Badge } from "@/components/ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { cn } from "@/lib/utils";

export function CitationLink({ 
  href, 
  children,
  ...props 
}: ComponentProps<"a">) {
  const domain = extractDomain(href ?? "");
  
  // Priority: children > domain
  const childrenText =
    typeof children === "string"
      ? children.replace(/^citation:\s*/i, "")
      : null;
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
            className="glass-button hover:bg-white/10 mx-0.5 cursor-pointer gap-1 rounded-full px-2 py-0.5 text-xs font-normal border-white/5 shadow-sm transition-all duration-300"
          >
            {displayText}
            <ExternalLinkIcon className="size-3" />
          </Badge>
        </a>
      </HoverCardTrigger>
      <HoverCardContent className={cn("relative w-80 p-0 glass-card border-white/10 overflow-hidden", props.className)}>
        <div className="p-4 bg-white/[0.02]">
          <div className="space-y-1">
            {displayText && (
              <h4 className="truncate font-semibold text-sm leading-tight text-foreground">
                {displayText}
              </h4>
            )}
            {href && (
              <p className="truncate break-all text-muted-foreground/80 text-xs">
                {href}
              </p>
            )}
          </div>
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary mt-3 inline-flex items-center gap-1.5 text-xs font-medium hover:underline transition-all"
          >
            زيارة المصدر
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
