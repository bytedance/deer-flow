"use client";

import {
  CircleCheckIcon,
  CircleStopIcon,
  Clock3Icon,
  ListChecksIcon,
  LoaderCircleIcon,
  MessageCircleQuestionIcon,
  TriangleAlertIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  isActiveBackgroundTask,
  type BackgroundTask,
  type BackgroundTaskStatus,
  useBackgroundTasks,
  useCancelBackgroundTask,
} from "@/core/background-tasks";
import { useI18n } from "@/core/i18n/hooks";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

export function ThreadBackgroundTasks({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const tasksQuery = useBackgroundTasks(threadId);
  const cancelTask = useCancelBackgroundTask(threadId);
  const tasks = tasksQuery.data ?? [];
  const activeTasks = tasks.filter(isActiveBackgroundTask);
  const recentTasks = tasks.filter((task) => !isActiveBackgroundTask(task));

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label={t.backgroundTasks.label}
          data-testid="background-tasks-trigger"
          className="relative"
        >
          <ListChecksIcon />
          <span className="hidden lg:inline">{t.backgroundTasks.label}</span>
          {activeTasks.length > 0 && (
            <span className="bg-primary text-primary-foreground grid size-4 place-items-center rounded-full text-[10px] font-semibold">
              {activeTasks.length > 9 ? "9+" : activeTasks.length}
            </span>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent className="w-[min(92vw,420px)] gap-0 p-0 sm:max-w-[420px]">
        <SheetHeader className="border-border border-b px-5 py-4">
          <SheetTitle className="flex items-center gap-2">
            <ListChecksIcon className="size-4" />
            {t.backgroundTasks.title}
          </SheetTitle>
          <SheetDescription>{t.backgroundTasks.description}</SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {tasksQuery.isLoading ? (
            <div
              role="status"
              className="text-muted-foreground flex items-center justify-center gap-2 py-12 text-sm"
            >
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t.common.loading}
            </div>
          ) : tasksQuery.isError ? (
            <div className="border-destructive/30 bg-destructive/5 rounded-xl border p-4 text-sm">
              <p className="text-destructive font-medium">
                {t.backgroundTasks.loadFailed}
              </p>
              <p className="text-muted-foreground mt-1 text-xs">
                {tasksQuery.error.message}
              </p>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="mt-3"
                onClick={() => void tasksQuery.refetch()}
              >
                {t.backgroundTasks.retry}
              </Button>
            </div>
          ) : tasks.length === 0 ? (
            <div className="text-muted-foreground flex flex-col items-center px-6 py-14 text-center">
              <ListChecksIcon className="mb-3 size-8 opacity-40" />
              <p className="text-foreground text-sm font-medium">
                {t.backgroundTasks.empty}
              </p>
              <p className="mt-1 text-xs">{t.backgroundTasks.emptyHint}</p>
            </div>
          ) : (
            <div className="space-y-5">
              {activeTasks.length > 0 && (
                <TaskSection
                  title={t.backgroundTasks.active}
                  tasks={activeTasks}
                  cancellingTaskId={
                    cancelTask.isPending ? cancelTask.variables : undefined
                  }
                  onCancel={(taskId) => cancelTask.mutate(taskId)}
                />
              )}
              {recentTasks.length > 0 && (
                <TaskSection
                  title={t.backgroundTasks.recent}
                  tasks={recentTasks}
                />
              )}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function TaskSection({
  title,
  tasks,
  cancellingTaskId,
  onCancel,
}: {
  title: string;
  tasks: BackgroundTask[];
  cancellingTaskId?: string;
  onCancel?: (taskId: string) => void;
}) {
  return (
    <section>
      <h3 className="text-muted-foreground mb-2 px-1 text-xs font-medium tracking-wide uppercase">
        {title}
      </h3>
      <div className="space-y-2">
        {tasks.map((task) => (
          <BackgroundTaskCard
            key={task.task_id}
            task={task}
            isCancelling={cancellingTaskId === task.task_id}
            onCancel={onCancel}
          />
        ))}
      </div>
    </section>
  );
}

function BackgroundTaskCard({
  task,
  isCancelling,
  onCancel,
}: {
  task: BackgroundTask;
  isCancelling: boolean;
  onCancel?: (taskId: string) => void;
}) {
  const { t } = useI18n();
  const active = isActiveBackgroundTask(task);
  const cancelling = active && (task.cancel_requested || isCancelling);
  const status = taskStatusPresentation(task.status, t.backgroundTasks.status);

  return (
    <article
      className="border-border bg-card rounded-xl border p-3 shadow-xs"
      data-testid={`background-task-${task.task_id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={task.task_name}>
            {task.task_name}
          </p>
          <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
            <span className="flex items-center gap-1">
              <Clock3Icon className="size-3" />
              {t.backgroundTasks.created(formatTimeAgo(task.created_at))}
            </span>
            <span>
              {t.backgroundTasks.updated(formatTimeAgo(task.updated_at))}
            </span>
          </div>
        </div>
        <Badge variant="outline" className={cn("shrink-0", status.className)}>
          <status.Icon
            className={cn("size-3", status.spinning && "animate-spin")}
          />
          {cancelling ? t.backgroundTasks.cancelling : status.label}
        </Badge>
      </div>

      {task.tracking_degraded && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-300">
          <TriangleAlertIcon className="size-3.5 shrink-0" />
          {t.backgroundTasks.trackingDegraded}
        </p>
      )}
      {task.error && (
        <p className="bg-destructive/5 text-destructive mt-2 rounded-md px-2 py-1.5 text-xs break-words">
          {task.error}
        </p>
      )}
      {active && onCancel && (
        <div className="mt-3 flex justify-end">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={cancelling}
            onClick={() => onCancel(task.task_id)}
          >
            {isCancelling && (
              <LoaderCircleIcon className="size-3.5 animate-spin" />
            )}
            {cancelling
              ? t.backgroundTasks.cancelling
              : t.backgroundTasks.cancel}
          </Button>
        </div>
      )}
    </article>
  );
}

type StatusTranslations = {
  submitted: string;
  working: string;
  inputRequired: string;
  completed: string;
  failed: string;
  cancelled: string;
};

function taskStatusPresentation(
  status: BackgroundTaskStatus,
  labels: StatusTranslations,
) {
  switch (status) {
    case "submitted":
      return {
        Icon: Clock3Icon,
        label: labels.submitted,
        className: "text-blue-700 dark:text-blue-300",
        spinning: false,
      };
    case "working":
      return {
        Icon: LoaderCircleIcon,
        label: labels.working,
        className: "text-blue-700 dark:text-blue-300",
        spinning: true,
      };
    case "input_required":
      return {
        Icon: MessageCircleQuestionIcon,
        label: labels.inputRequired,
        className: "text-amber-700 dark:text-amber-300",
        spinning: false,
      };
    case "completed":
      return {
        Icon: CircleCheckIcon,
        label: labels.completed,
        className: "text-emerald-700 dark:text-emerald-300",
        spinning: false,
      };
    case "failed":
      return {
        Icon: TriangleAlertIcon,
        label: labels.failed,
        className: "text-destructive",
        spinning: false,
      };
    case "cancelled":
      return {
        Icon: CircleStopIcon,
        label: labels.cancelled,
        className: "text-muted-foreground",
        spinning: false,
      };
  }
}
