"use client";

import { BellIcon, BellOffIcon } from "lucide-react";

import type { ChannelProvider } from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

/**
 * Whether scheduled-task updates reach this app ("Scheduled task updates:
 * sent here" / "... not available for this app yet"). Only providers that
 * implement proactive push receive them (WeCom today). Renders nothing for
 * an older backend that does not report `proactive_notifications`, rather
 * than claiming an app it cannot judge is unsupported.
 */
export function ChannelScheduledUpdates({
  provider,
  className,
}: {
  provider: Pick<ChannelProvider, "proactive_notifications">;
  className?: string;
}) {
  const { t } = useI18n();
  if (typeof provider.proactive_notifications !== "boolean") {
    return null;
  }
  const supported = provider.proactive_notifications;
  const Icon = supported ? BellIcon : BellOffIcon;
  return (
    <p
      data-testid="channel-scheduled-updates"
      data-supported={supported ? "true" : "false"}
      className={cn(
        "text-muted-foreground flex items-start gap-1.5 text-xs",
        className,
      )}
    >
      <Icon className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>
        {supported
          ? t.channels.scheduledUpdates.supported
          : t.channels.scheduledUpdates.unsupported}
      </span>
    </p>
  );
}
