"use client";

import { Clock3, Puzzle } from "lucide-react";
import type { ReactNode } from "react";

import { ChannelProviderIcon } from "@/components/workspace/channels/channel-provider-icon";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { labelOfThreadOrigin, type ThreadOrigin } from "@/core/threads/origin";
import type { ChannelThreadSource } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

type ThreadOriginIconProps = {
  origin: ThreadOrigin | null;
  className?: string;
};

/**
 * Who created a thread, as a small icon before its title: a clock for a
 * scheduled run, the provider's mark for an IM or GitHub thread, a puzzle
 * piece for an extension. The localized label ("Scheduled run", "From
 * Feishu", ...) is the icon's accessible name and tooltip. Renders nothing
 * for the user's own chats and for origins without a marker
 * (`mcp_notification` runs never create threads).
 */
export function ThreadOriginIcon({ origin, className }: ThreadOriginIconProps) {
  const { t } = useI18n();
  const label = labelOfThreadOrigin(origin, t);
  if (!origin || !label) {
    return null;
  }

  let icon: ReactNode;
  switch (origin.kind) {
    case "schedule":
      icon = <Clock3 aria-hidden="true" className="size-4" />;
      break;
    case "extension":
      icon = <Puzzle aria-hidden="true" className="size-4" />;
      break;
    case "im_channel":
    case "github":
      icon = (
        <ChannelProviderIcon provider={origin.provider} className="size-4" />
      );
      break;
    default:
      return null;
  }

  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      data-origin-kind={origin.kind}
      data-testid="thread-origin-icon"
      className={cn("inline-flex shrink-0 items-center", className)}
    >
      {icon}
    </span>
  );
}

type ThreadChannelIconProps = {
  source: ChannelThreadSource | null;
  className?: string;
};

/** The provider icon of an IM channel thread: a `ThreadOriginIcon` for its provider. */
export function ThreadChannelIcon({
  source,
  className,
}: ThreadChannelIconProps) {
  if (!source) {
    return null;
  }
  return (
    <ThreadOriginIcon
      origin={
        source.provider === "github"
          ? { kind: "github", provider: "github" }
          : { kind: "im_channel", provider: source.provider }
      }
      className={className}
    />
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
  const { t } = useI18n();
  if (!source) {
    return null;
  }

  return (
    <span
      className={cn(
        "bg-muted text-muted-foreground inline-flex h-6 max-w-32 items-center gap-1 rounded-md px-2 text-xs font-medium",
        className,
      )}
      title={t.threads.origin.fromProvider(source.label)}
    >
      <ChannelProviderIcon provider={source.provider} className="size-3.5" />
      <span className="truncate">{source.label}</span>
    </span>
  );
}

/**
 * Row `aria-label` of an unread thread: "{title}, unread" / "{title}，未读".
 * With an origin marker its label comes first ("Scheduled run, {title},
 * unread" / "来自飞书，{title}，未读"), so the label that replaces the row's
 * content does not drop who created the thread.
 */
export function unreadLabelOfThread(
  title: string,
  t: Pick<Translations, "threads">,
  origin: ThreadOrigin | null = null,
): string {
  const originLabel = labelOfThreadOrigin(origin, t);
  if (originLabel) {
    return t.threads.unreadLabelWithOrigin
      .replace("{origin}", () => originLabel)
      .replace("{title}", () => title);
  }
  return t.threads.unreadLabel.replace("{title}", () => title);
}

/**
 * The unread dot after a thread's title: a decorative dot plus the sr-only
 * "Unread", so the state is announced even where the row has no label of
 * its own. Callers never render it for the thread that is open.
 */
export function ThreadUnreadDot({ className }: { className?: string }) {
  const { t } = useI18n();
  return (
    <span
      data-testid="thread-unread-dot"
      title={t.threads.unread}
      className={cn("inline-flex shrink-0 items-center", className)}
    >
      <span aria-hidden="true" className="bg-primary size-1.5 rounded-full" />
      <span className="sr-only">{t.threads.unread}</span>
    </span>
  );
}
