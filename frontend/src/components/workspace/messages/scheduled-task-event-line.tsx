"use client";

import {
  ChevronRight,
  CircleCheck,
  CircleX,
  PauseCircle,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { Fragment, useId } from "react";

import { useI18n } from "@/core/i18n/hooks";
import {
  describeTaskEvent,
  sentenceGap,
  type ScheduledTaskEvent,
  type TaskEventKind,
} from "@/core/scheduled-tasks/events";
import { browserTimeZone, formatTaskTime } from "@/core/scheduled-tasks/format";
import { cn } from "@/lib/utils";

const ICONS: Record<TaskEventKind, LucideIcon> = {
  stopped: PauseCircle,
  autoPaused: PauseCircle,
  finished: CircleCheck,
  onceDone: CircleCheck,
  onceFailed: CircleX,
};

/**
 * One lifecycle event of a chat-created schedule, shown in the chat that
 * created it (mockup m2, marker 4): "Release checklist was paused by the
 * agent …  Today 09:01   See that run ›". The line is history: it stays when
 * the task is later deleted ("Open task" then shows the deleted state).
 * "See that run" opens the run chat on the route of the agent that ran it,
 * recorded with the event; a task's agent can change after it is created.
 */
export function ScheduledTaskEventLine({
  event,
  className,
}: {
  event: ScheduledTaskEvent;
  className?: string;
}) {
  const { t, locale } = useI18n();
  const textId = useId();
  const description = describeTaskEvent(event, t);
  if (!description) {
    return null;
  }

  const Icon = ICONS[description.kind];
  const href = description.action.href;
  const time = formatTaskTime(event.created_at, {
    timeZone: browserTimeZone(),
    locale,
    labels: t.scheduledTasks.time,
  });
  const main = description.segments.map((segment) => segment.text).join("");
  // A separate sentence, with a stop added after a bare stop condition.
  const suffixGap = description.suffix
    ? sentenceGap(main, description.suffix)
    : "";

  return (
    <div
      role="note"
      aria-label={t.scheduledTasks.events.label}
      data-testid="scheduled-task-event-line"
      data-task-id={event.task_id}
      data-event-id={event.id}
      data-event-kind={description.kind}
      className={cn(
        "bg-muted/40 text-muted-foreground flex w-full items-start gap-2.5 rounded-lg border border-dashed px-3 py-2 text-sm",
        className,
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 size-4 shrink-0",
          description.kind === "onceFailed" && "text-destructive",
        )}
        aria-hidden
      />
      <p
        id={textId}
        className="text-foreground/80 min-w-0 flex-1 break-words"
        data-testid="scheduled-task-event-text"
      >
        {description.segments.map((segment, index) =>
          segment.kind === "title" ? (
            <strong key={index} className="text-foreground font-medium">
              {segment.text}
            </strong>
          ) : segment.kind === "condition" ? (
            // Clamped to one line; the full text is in the tooltip.
            <span
              key={index}
              title={segment.text}
              data-testid="scheduled-task-event-condition"
              className="inline-block max-w-full truncate align-bottom"
            >
              {segment.text}
            </span>
          ) : (
            <Fragment key={index}>{segment.text}</Fragment>
          ),
        )}
        {description.suffix && (
          <>
            {suffixGap}
            {description.suffix}
          </>
        )}
        {/* A real space, so the accessible text (the link's description)
            keeps the sentence and the time apart. */}
        {time && " "}
        {time && (
          <time
            dateTime={event.created_at}
            className="text-muted-foreground ml-1 text-xs whitespace-nowrap"
          >
            {time}
          </time>
        )}
      </p>
      <Link
        href={href}
        data-testid="scheduled-task-event-action"
        data-action={description.action.kind}
        // Several lines can each say "See that run": tell them apart.
        aria-describedby={textId}
        className="text-foreground/80 hover:text-foreground inline-flex shrink-0 items-center gap-0.5 self-center text-xs font-medium whitespace-nowrap hover:underline"
      >
        {description.action.label}
        <ChevronRight className="size-3.5" aria-hidden />
      </Link>
    </div>
  );
}
