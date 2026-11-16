"use client";

import { GhostIcon, XIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { incognitoLifetimeParts } from "@/core/threads/incognito";

import { Tooltip } from "../tooltip";

export interface IncognitoNoticesProps {
  /**
   * Idle window from `/api/features`, or `null` when it could not be read.
   * The UI never states a lifetime the server did not report.
   */
  idleTtlSeconds: number | null;
}

/**
 * The full-width shell of an incognito chat: a dark top bar around a framed,
 * lightly-filled conversation area. The workspace sidebar and the ordinary
 * chat header are not part of this surface.
 */
export function IncognitoShell({
  onEnd,
  children,
}: {
  /** End the chat and leave; the Gateway purges it after the grace period. */
  onEnd: () => void;
  children: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="bg-incognito flex size-full min-h-0 flex-col">
      <div className="text-incognito-foreground flex h-14 shrink-0 items-center gap-2.5 pr-4 pl-5">
        <GhostIcon aria-hidden="true" className="size-[18px]" />
        <span className="text-[15px] font-medium">{t.incognito.label}</span>
        <Tooltip content={t.incognito.end}>
          <Button
            aria-label={t.incognito.end}
            className="text-incognito-foreground hover:bg-incognito-foreground/10 ml-auto"
            onClick={onEnd}
            size="icon-sm"
            type="button"
            variant="ghost"
          >
            <XIcon />
          </Button>
        </Tooltip>
      </div>
      <div className="bg-incognito min-h-0 flex-1 px-2.5 pb-2.5">
        <div
          className="bg-incognito-surface flex size-full min-h-0 flex-col overflow-hidden rounded-[20px]"
          data-testid="incognito-frame"
        >
          {children}
        </div>
      </div>
    </div>
  );
}

/** The centered heading of an empty incognito chat. */
export function IncognitoTitle() {
  const { t } = useI18n();
  return (
    <div className="pb-8 text-center text-3xl font-medium text-balance">
      {t.incognito.title}
    </div>
  );
}

/**
 * What the chat never enters and when it disappears, plus the third-party
 * boundary. Rendered under the composer inside the frame.
 */
export function IncognitoNotices({ idleTtlSeconds }: IncognitoNoticesProps) {
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
      className="text-muted-foreground mx-auto mt-4 max-w-xl space-y-1 text-center text-[13px] leading-relaxed"
      data-testid="incognito-notices"
    >
      <p>
        {duration === null
          ? t.incognito.noticesUnknown
          : t.incognito.notices(duration)}
      </p>
      <p className="text-muted-foreground/70 text-xs">
        {t.incognito.boundaryNotice}
      </p>
    </div>
  );
}
