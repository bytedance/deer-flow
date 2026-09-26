"use client";

import { ChannelProviderIcon } from "@/components/workspace/channels/channel-provider-icon";
import type { ChannelThreadSource } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

type ThreadChannelIconProps = {
  source: ChannelThreadSource | null;
  className?: string;
};

export function ThreadChannelIcon({
  source,
  className,
}: ThreadChannelIconProps) {
  if (!source) {
    return null;
  }

  return (
    <span
      aria-label={`${source.label} channel`}
      title={`${source.label} channel`}
      className={cn("inline-flex shrink-0 items-center", className)}
    >
      <ChannelProviderIcon provider={source.provider} className="size-4" />
    </span>
  );
}

type ThreadChannelBadgeProps = {
  source: ChannelThreadSource | null;
  className?: string;
};

export function ThreadChannelBadge({
  source,
  className,
}: ThreadChannelBadgeProps) {
  if (!source) {
    return null;
  }

  return (
    <span
      className={cn(
        "bg-muted text-muted-foreground inline-flex h-6 max-w-32 items-center gap-1 rounded-md px-2 text-xs font-medium",
        className,
      )}
      title={`${source.label} channel`}
    >
      <ChannelProviderIcon provider={source.provider} className="size-3.5" />
      <span className="truncate">{source.label}</span>
    </span>
  );
}
