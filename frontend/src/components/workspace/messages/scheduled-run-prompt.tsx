"use client";

import { ArrowUpRight, CalendarClock, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { fill } from "@/components/workspace/scheduled-tasks/shared";
import { useI18n } from "@/core/i18n/hooks";
import {
  browserTimeZone,
  displayTimeZone,
  formatWithViewerTime,
} from "@/core/scheduled-tasks/format";
import type { ScheduledOrigin } from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

import { taskPagePath } from "./scheduled-task-card";

/**
 * Zone a run's time is shown in, by the same rule as the tasks page
 * (`displayTimeZone`): interval tasks read in the viewer's zone (a chat may
 * have stored the placeholder "UTC"); every other task uses its own zone.
 * Launches recorded before the origin carried the schedule type fall back to
 * treating "UTC" as the placeholder.
 */
function originTimeZone(origin: ScheduledOrigin): string {
  if (origin.schedule_type) {
    return displayTimeZone({
      schedule_type: origin.schedule_type,
      timezone: origin.timezone,
    });
  }
  return !origin.timezone || origin.timezone === "UTC"
    ? browserTimeZone()
    : origin.timezone;
}

/**
 * The automatic prompt of a scheduled or trial run (mockup m3): one header
 * line naming the task, the run and its time, and the task instructions in a
 * collapsed line. It renders the user-language parts from the launch origin,
 * never the launched message text, which also holds host-written English
 * (the stop-rule paragraph and the notes wrapper). Not editable.
 */
export function ScheduledRunPrompt({
  origin,
  className,
}: {
  origin: ScheduledOrigin;
  className?: string;
}) {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const rt = st.runThread;
  const [open, setOpen] = useState(false);
  const kind = origin.trigger === "manual" ? rt.trialRun : rt.scheduledRun;
  const when = origin.scheduled_for
    ? formatWithViewerTime(origin.scheduled_for, originTimeZone(origin), {
        locale,
        labels: st.time,
      })
    : "";
  const notes = origin.standing_notes.filter((note) => note.trim());

  return (
    <div
      className={cn("flex w-full flex-col gap-2", className)}
      data-testid="scheduled-run-prompt"
      data-task-id={origin.task_id}
    >
      <div className="bg-card flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-2.5 text-sm">
        <CalendarClock className="size-4 shrink-0" aria-hidden />
        <span className="font-medium">{kind}</span>
        <span className="min-w-0 break-words">
          {origin.task_title}
          {origin.run_number != null && (
            <>
              <span aria-hidden> · </span>
              {fill(rt.runNumber, { n: origin.run_number })}
            </>
          )}
        </span>
        {when && <span className="text-muted-foreground">{when}</span>}
        <Link
          href={taskPagePath(origin.task_id)}
          className="ml-auto inline-flex items-center gap-1 text-sm font-medium hover:underline"
        >
          {rt.openTask}
          <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      </div>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-1 border-l-2 pl-3 text-left text-sm">
          <ChevronRight
            className={cn(
              "size-4 shrink-0 transition-transform",
              open && "rotate-90",
            )}
            aria-hidden
          />
          {rt.instructions}
        </CollapsibleTrigger>
        <CollapsibleContent className="text-muted-foreground mt-2 space-y-2 border-l-2 pl-8 text-sm">
          <p
            className="break-words whitespace-pre-wrap"
            data-testid="scheduled-run-instructions"
          >
            {origin.instructions}
          </p>
          {origin.stop_condition?.trim() && (
            <p className="break-words">
              {fill(rt.stopsWhen, { condition: origin.stop_condition })}
            </p>
          )}
          {notes.length > 0 && (
            <div>
              <p>{rt.notes}</p>
              <ul className="list-disc pl-4">
                {notes.map((note, index) => (
                  <li key={index} className="break-words">
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
