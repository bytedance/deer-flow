"use client";

import { VenetianMaskIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { incognitoLifetimeParts } from "@/core/threads/incognito";

export interface IncognitoFrameProps {
  /**
   * Idle window from `/api/features`, or `null` when it could not be read.
   * The UI never states a lifetime the server did not report.
   */
  idleTtlSeconds: number | null;
  /** End the chat and leave; the Gateway purges it after the grace period. */
  onEnd: () => void;
}

/**
 * The dark frame at the top of an incognito chat with its two notices: what
 * the chat never enters, and when it disappears. The `×` control ends it.
 */
export function IncognitoFrame({ idleTtlSeconds, onEnd }: IncognitoFrameProps) {
  const { t } = useI18n();
  const parts =
    idleTtlSeconds === null ? null : incognitoLifetimeParts(idleTtlSeconds);
  const duration =
    parts === null
      ? null
      : parts.unit === "days"
        ? t.incognito.durationDays(parts.count)
        : parts.unit === "hours"
          ? t.incognito.durationHours(parts.count)
          : t.incognito.durationMinutes(parts.count);

  return (
    <div
      className="border-incognito-border bg-incognito text-incognito-foreground flex items-start gap-3 rounded-xl border px-3 py-2.5 shadow-xs"
      data-testid="incognito-frame"
    >
      <VenetianMaskIcon
        aria-hidden="true"
        className="text-incognito-muted-foreground mt-0.5 size-4 shrink-0"
      />
      <div className="min-w-0 flex-1 space-y-0.5 text-sm leading-snug">
        <p>{t.incognito.privacyNotice}</p>
        <p className="text-incognito-muted-foreground text-xs">
          {duration === null
            ? t.incognito.lifetimeUnknown
            : t.incognito.lifetimeNotice(duration)}
        </p>
      </div>
      <Button
        aria-label={t.incognito.end}
        className="text-incognito-muted-foreground hover:bg-incognito-foreground/10 hover:text-incognito-foreground -my-1 -mr-1 shrink-0"
        onClick={onEnd}
        size="icon-sm"
        type="button"
        variant="ghost"
      >
        <XIcon />
      </Button>
    </div>
  );
}
