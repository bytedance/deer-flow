"use client";

import { Clock3Icon } from "lucide-react";
import { useEffect, useState } from "react";

import { Shimmer } from "@/components/ai-elements/shimmer";
import { useI18n } from "@/core/i18n/hooks";
import { formatRunDuration } from "@/core/messages/run-duration";

export function RunActivity({ startTime }: { startTime: number | null }) {
  const { t } = useI18n();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (startTime === null) {
      setElapsed(0);
      return;
    }

    const updateElapsed = () => {
      setElapsed(Math.max(0, Math.floor((Date.now() - startTime) / 1000)));
    };
    updateElapsed();
    const interval = setInterval(updateElapsed, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  const formatted = formatRunDuration(elapsed, t.runDuration);

  return (
    <div
      className="text-muted-foreground flex items-center gap-2 text-sm"
      data-testid="run-activity"
    >
      <Clock3Icon className="size-4" />
      <Shimmer duration={1}>{t.runDuration.working}</Shimmer>
      {formatted && <span aria-hidden="true">({formatted})</span>}
    </div>
  );
}

export function RunDuration({ durationSeconds }: { durationSeconds: number }) {
  const { t } = useI18n();
  const formatted = formatRunDuration(durationSeconds, t.runDuration);
  if (!formatted) {
    return null;
  }

  return (
    <div
      className="text-muted-foreground flex items-center gap-2 text-sm"
      data-testid="run-duration"
      title={t.runDuration.description}
    >
      <Clock3Icon className="size-4" />
      <span>{t.runDuration.completedIn(formatted)}</span>
    </div>
  );
}
