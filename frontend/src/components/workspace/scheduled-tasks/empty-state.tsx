"use client";

import { CalendarClock, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

import { WithReason } from "./shared";

/** "New task"; disabled with the reason while automatic runs are off. */
export function NewTaskButton({
  createBlocked,
  onClick,
  variant = "default",
}: {
  createBlocked: boolean;
  onClick: () => void;
  variant?: "default" | "outline";
}) {
  const { t } = useI18n();
  const st = t.scheduledTasks;
  return (
    <WithReason reason={createBlocked ? st.page.createBlocked : null}>
      <Button
        variant={variant}
        size="sm"
        disabled={createBlocked}
        onClick={onClick}
        data-testid="scheduled-task-new"
      >
        <Plus aria-hidden />
        {st.page.newTask}
      </Button>
    </WithReason>
  );
}

/** First visit: what scheduled tasks are and how to make one. */
export function EmptyState({
  toolEnabled,
  createBlocked,
  onCreate,
}: {
  toolEnabled: boolean;
  createBlocked: boolean;
  onCreate: () => void;
}) {
  const { t } = useI18n();
  const st = t.scheduledTasks;
  return (
    <div
      className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-12 text-center"
      data-testid="scheduled-task-empty"
    >
      <span className="bg-muted text-muted-foreground flex size-10 items-center justify-center rounded-full">
        <CalendarClock className="size-5" aria-hidden />
      </span>
      <h2 className="text-base font-semibold">{st.page.emptyTitle}</h2>
      <p className="text-muted-foreground max-w-md text-sm">
        {toolEnabled ? st.page.emptyBody : st.page.emptyBodyNoChat}
      </p>
      <NewTaskButton createBlocked={createBlocked} onClick={onCreate} />
    </div>
  );
}
