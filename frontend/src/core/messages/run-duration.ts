import type { Message } from "@langchain/langgraph-sdk";

import type { MessageGroup } from "./utils";

export interface RunDurationDisplay {
  runId: string;
  durationSeconds: number;
}

export interface RunDurationFormatter {
  lessThanSecond: string;
  hours: (value: number) => string;
  minutes: (value: number) => string;
  seconds: (value: number) => string;
  separator: string;
}

type MessageWithRunId = Message & { run_id?: unknown };

export function getMessageRunId(message: Message): string | undefined {
  const runId = (message as MessageWithRunId).run_id;
  return typeof runId === "string" && runId.length > 0 ? runId : undefined;
}

function normalizeDuration(value: unknown): number | undefined {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return undefined;
  }
  return Math.floor(value);
}

/**
 * Locate the single UI position that owns each completed run's wall-clock
 * duration. The backend keeps the value on every AI message for compatibility,
 * but the UI treats it as run-scoped metadata owned by the last visible
 * group belonging to that run.
 */
export function getRunDurationDisplaysByGroupIndex(
  groups: MessageGroup[],
): RunDurationDisplay[][] {
  const displays = groups.map(() => [] as RunDurationDisplay[]);
  const durationByRunId = new Map<string, number>();
  const lastGroupIndexByRunId = new Map<string, number>();

  groups.forEach((group, groupIndex) => {
    for (const message of group.messages) {
      const runId = getMessageRunId(message);
      if (!runId) {
        continue;
      }

      lastGroupIndexByRunId.set(runId, groupIndex);
      if (message.type !== "ai") {
        continue;
      }

      const duration = normalizeDuration(
        message.additional_kwargs?.turn_duration,
      );
      if (duration !== undefined) {
        durationByRunId.set(runId, duration);
      }
    }
  });

  for (const [runId, durationSeconds] of durationByRunId) {
    const groupIndex = lastGroupIndexByRunId.get(runId);
    if (groupIndex !== undefined) {
      displays[groupIndex]?.push({ runId, durationSeconds });
    }
  }

  return displays;
}

const ISO_TIMEZONE_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

/**
 * Parse a run's `created_at` into epoch milliseconds. The backend measures
 * `turn_duration` from this timestamp and reads offset-less values as UTC, so
 * the live elapsed time does the same instead of using the browser's zone.
 */
export function parseRunStartTime(createdAt: unknown): number | null {
  if (typeof createdAt !== "string") {
    return null;
  }
  const value = createdAt.trim();
  if (!value) {
    return null;
  }
  const time = Date.parse(
    ISO_TIMEZONE_SUFFIX.test(value) ? value : `${value}Z`,
  );
  return Number.isFinite(time) ? time : null;
}

export function formatRunDuration(
  value: number,
  formatter: RunDurationFormatter,
): string | null {
  const duration = normalizeDuration(value);
  if (duration === undefined) {
    return null;
  }
  if (duration === 0) {
    return formatter.lessThanSecond;
  }

  const hours = Math.floor(duration / 3600);
  const minutes = Math.floor((duration % 3600) / 60);
  const seconds = duration % 60;
  const parts: string[] = [];

  if (hours > 0) {
    parts.push(formatter.hours(hours));
  }
  if (minutes > 0) {
    parts.push(formatter.minutes(minutes));
  }
  if (seconds > 0) {
    parts.push(formatter.seconds(seconds));
  }

  return parts.join(formatter.separator);
}
