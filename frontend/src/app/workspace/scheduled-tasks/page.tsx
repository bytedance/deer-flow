"use client";

import { CalendarClock, Plus } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import {
  useUpdateScheduledTask,
  useDeleteScheduledTask,
  usePauseScheduledTask,
  useResumeScheduledTask,
  useScheduledTaskRuns,
  useScheduledTasks,
  useTriggerScheduledTask,
  useThreadScheduledTasks,
} from "@/core/scheduled-tasks/hooks";
import type {
  ScheduledTask,
  ScheduledTaskRun,
} from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

const NONE = "—";

function formatTimestamp(value: string | null, locale: string): string {
  if (!value) {
    return NONE;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const intlLocale = locale === "zh-CN" ? "zh-CN" : "en-US";
  return new Intl.DateTimeFormat(intlLocale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

const STATUS_DOT: Record<string, string> = {
  enabled: "bg-emerald-500",
  running: "bg-sky-500",
  paused: "bg-amber-500",
  completed: "bg-zinc-400",
  failed: "bg-rose-500",
  cancelled: "bg-zinc-400",
};

function StatusBadge({
  status,
  statusLabel,
}: {
  status: string;
  statusLabel: (v: string) => string;
}) {
  const dot = STATUS_DOT[status] ?? "bg-zinc-400";
  return (
    <span className="text-muted-foreground inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-xs font-medium">
      <span aria-hidden className={cn("size-1.5 rounded-full", dot)} />
      {statusLabel(status)}
    </span>
  );
}

export default function ScheduledTasksPage() {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const router = useRouter();
  const searchParams = useSearchParams();
  const threadId = searchParams.get("thread_id");
  const allTasksQuery = useScheduledTasks();
  const threadTasksQuery = useThreadScheduledTasks(threadId);
  const data = threadId ? threadTasksQuery.data : allTasksQuery.data;
  const queryError = threadId ? threadTasksQuery.error : allTasksQuery.error;
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<
    "all" | "enabled" | "paused" | "running" | "completed" | "failed"
  >("all");
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [editSchedule, setEditSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
  });
  const hasTasks = (data ?? []).length > 0;
  const filteredData = (data ?? []).filter((task) => {
    return statusFilter === "all" || task.status === statusFilter;
  });
  const selectedTask =
    filteredData.find((task) => task.id === selectedTaskId) ?? null;
  const taskRunsQuery = useScheduledTaskRuns(selectedTask?.id);
  const updateTask = useUpdateScheduledTask(selectedTask?.id ?? "");
  const pauseTask = usePauseScheduledTask();
  const resumeTask = useResumeScheduledTask();
  const triggerTask = useTriggerScheduledTask();
  const deleteTask = useDeleteScheduledTask();

  const scheduleTypeLabel = (v: string) =>
    v === "cron"
      ? st.scheduleType.cron
      : v === "once"
        ? st.scheduleType.once
        : v;
  const statusLabel = (v: string) =>
    (st.status as Record<string, string>)[v] ?? v;
  const contextModeLabel = (v: string) =>
    v === "fresh_thread_per_run"
      ? st.context.fresh
      : v === "reuse_thread"
        ? st.context.reuse
        : v;
  const runTriggerLabel = (v: string) =>
    (st.runTrigger as Record<string, string>)[v] ?? v;
  const runStatusLabel = (v: string) =>
    (st.runStatus as Record<string, string>)[v] ?? v;
  const runSummary = (run: ScheduledTaskRun) =>
    `${runTriggerLabel(run.trigger)} · ${runStatusLabel(run.status)}`;
  useEffect(() => {
    document.title = `${t.sidebar.scheduledTasks} - ${t.pages.appName}`;
  }, [t.pages.appName, t.sidebar.scheduledTasks]);

  useEffect(() => {
    if (!selectedTaskId) {
      return;
    }
    const stillVisible = filteredData.some(
      (task) => task.id === selectedTaskId,
    );
    if (!stillVisible) {
      setSelectedTaskId(null);
      setDetailOpen(false);
      setEditing(false);
    }
  }, [filteredData, selectedTaskId]);

  useEffect(() => {
    if (!selectedTask) {
      setEditing(false);
      return;
    }
    setEditTitle(selectedTask.title);
    setEditPrompt(selectedTask.prompt);
    const spec = selectedTask.schedule_spec as {
      cron?: string;
      run_at?: string;
    };
    setEditSchedule({
      schedule_type: selectedTask.schedule_type,
      schedule_spec: {
        cron: typeof spec.cron === "string" ? spec.cron : undefined,
        run_at: typeof spec.run_at === "string" ? spec.run_at : undefined,
      },
      timezone: selectedTask.timezone || "UTC",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTask?.id]);

  const createHref = threadId
    ? `/workspace/scheduled-tasks/new?thread_id=${encodeURIComponent(threadId)}`
    : "/workspace/scheduled-tasks/new";

  const statusFilters = [
    { id: "enabled" as const, label: st.filters.enabled },
    { id: "paused" as const, label: st.filters.paused },
  ];

  const openDetail = (taskId: string) => {
    setSelectedTaskId(taskId);
    setDetailOpen(true);
  };

  return (
    <WorkspaceContainer>
      <header className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">{st.title}</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            {st.description}
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => router.push(createHref)}
          data-testid="scheduled-task-create-toggle"
        >
          <Plus className="mr-1.5 h-4 w-4" />
          {st.create.title}
        </Button>
      </header>
      <WorkspaceBody>
        <div className="mx-auto w-full max-w-(--container-width-md) p-6">
          {threadId && (
            <div className="text-muted-foreground mb-4 text-sm">
              {st.detail.filteredByThread.replace("{id}", threadId)}
            </div>
          )}
          {queryError ? (
            <div
              className="text-destructive text-sm"
              data-testid="scheduled-task-load-error"
            >
              {st.detail.loadFailed}: {queryError.message}
            </div>
          ) : null}
          {hasTasks ? (
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <div className="bg-muted/40 flex items-center gap-1 rounded-lg border p-1">
                {statusFilters.map((f) => (
                  <FilterChip
                    key={f.id}
                    active={statusFilter === f.id}
                    onClick={() =>
                      setStatusFilter(statusFilter === f.id ? "all" : f.id)
                    }
                  >
                    {f.label}
                  </FilterChip>
                ))}
              </div>
            </div>
          ) : null}
<<<<<<< HEAD
          {isLoading ? (
            <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
              {t.common.loading}
            </div>
          ) : filteredData.length === 0 ? (
=======
          {filteredData.length === 0 ? (
>>>>>>> 35b57c28 (fix(frontend): mount SkinProvider in workspace and showcase layouts)
            queryError ? null : hasTasks ? (
              <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
                <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
                  <CalendarClock className="text-muted-foreground h-7 w-7" />
                </div>
                <div>
                  <p className="font-medium">{st.detail.noMatchesTitle}</p>
                  <p className="text-muted-foreground mt-1 text-sm">
                    {st.detail.noMatchesDescription}
                  </p>
                </div>
              </div>
            ) : (
              <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
                <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
                  <CalendarClock className="text-muted-foreground h-7 w-7" />
                </div>
                <div>
                  <p className="font-medium">{st.detail.noTasksTitle}</p>
                  <p className="text-muted-foreground mt-1 text-sm">
                    {st.detail.noTasksDescription}
                  </p>
                </div>
                <Button
                  variant="outline"
                  className="mt-2"
                  onClick={() => router.push(createHref)}
                >
                  <Plus className="mr-1.5 h-4 w-4" />
                  {st.create.title}
                </Button>
              </div>
            )
          ) : (
            <div
              data-testid="scheduled-task-list"
              className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
            >
              {filteredData.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onClick={() => openDetail(task.id)}
                  status={task.status}
                  statusLabel={statusLabel}
                  scheduleTypeLabel={scheduleTypeLabel(task.schedule_type)}
                  nextRun={formatTimestamp(task.next_run_at, locale)}
                />
              ))}
            </div>
          )}
        </div>
      </WorkspaceBody>

      {/* Task detail dialog */}
      <Dialog
        open={detailOpen}
        onOpenChange={(open) => {
          setDetailOpen(open);
          if (!open) setEditing(false);
        }}
      >
        <DialogContent className="sm:max-w-lg">
          {selectedTask ? (
            <TaskDetail
              task={selectedTask}
              editing={editing}
              setEditing={setEditing}
              editTitle={editTitle}
              setEditTitle={setEditTitle}
              editPrompt={editPrompt}
              setEditPrompt={setEditPrompt}
              editSchedule={editSchedule}
              setEditSchedule={setEditSchedule}
              updateTask={updateTask}
              pauseTask={pauseTask}
              resumeTask={resumeTask}
              triggerTask={triggerTask}
              setDeleteOpen={setDeleteOpen}
              taskRunsQuery={taskRunsQuery}
              st={st}
              t={t}
              locale={locale}
              contextModeLabel={contextModeLabel}
              scheduleTypeLabel={scheduleTypeLabel}
              formatTimestamp={formatTimestamp}
              runSummary={runSummary}
              statusLabel={statusLabel}
              NONE={NONE}
            />
          ) : null}
        </DialogContent>
      </Dialog>

      {/* Delete confirm */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{st.actions.delete}</DialogTitle>
            <DialogDescription>{st.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteTask.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (selectedTask) {
                  deleteTask.mutate(selectedTask.id, {
                    onSuccess: () => {
                      setDeleteOpen(false);
                      setDetailOpen(false);
                    },
                  });
                }
              }}
              disabled={deleteTask.isPending}
            >
              {deleteTask.isPending ? t.common.loading : st.actions.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </WorkspaceContainer>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground shadow-sm"
          : "text-muted-foreground hover:bg-secondary hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function TaskCard({
  task,
  onClick,
  status,
  statusLabel,
  scheduleTypeLabel,
  nextRun,
}: {
  task: ScheduledTask;
  onClick: () => void;
  status: string;
  statusLabel: (v: string) => string;
  scheduleTypeLabel: string;
  nextRun: string;
}) {
  const dot = STATUS_DOT[task.status] ?? "bg-zinc-400";
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={`scheduled-task-item-${task.id}`}
      className="bg-card hover:bg-secondary/40 flex flex-col gap-3 rounded-lg border p-4 text-left transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 text-sm leading-snug font-semibold">
          {task.title}
        </span>
        <span
          aria-hidden
          className={cn("mt-1 size-2 shrink-0 rounded-full", dot)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="text-muted-foreground text-xs">
          {scheduleTypeLabel}
        </span>
        <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs tabular-nums">
          <CalendarClock className="size-3.5" />
          {nextRun}
        </span>
      </div>
      <div className="border-t pt-2">
        <StatusBadge status={status} statusLabel={statusLabel} />
      </div>
    </button>
  );
}

function TaskDetail({
  task,
  editing,
  setEditing,
  editTitle,
  setEditTitle,
  editPrompt,
  setEditPrompt,
  editSchedule,
  setEditSchedule,
  updateTask,
  pauseTask,
  resumeTask,
  triggerTask,
  setDeleteOpen,
  taskRunsQuery,
  st,
  t,
  locale,
  contextModeLabel,
  scheduleTypeLabel,
  formatTimestamp,
  runSummary,
  statusLabel,
  NONE,
}: {
  task: ScheduledTask;
  editing: boolean;
  setEditing: (v: boolean) => void;
  editTitle: string;
  setEditTitle: (v: string) => void;
  editPrompt: string;
  setEditPrompt: (v: string) => void;
  editSchedule: ScheduleValue;
  setEditSchedule: (v: ScheduleValue) => void;
  updateTask: ReturnType<typeof useUpdateScheduledTask>;
  pauseTask: ReturnType<typeof usePauseScheduledTask>;
  resumeTask: ReturnType<typeof useResumeScheduledTask>;
  triggerTask: ReturnType<typeof useTriggerScheduledTask>;
  setDeleteOpen: (v: boolean) => void;
  taskRunsQuery: ReturnType<typeof useScheduledTaskRuns>;
  st: Translations["scheduledTasks"];
  t: Translations;
  locale: string;
  contextModeLabel: (v: string) => string;
  scheduleTypeLabel: (v: string) => string;
  formatTimestamp: (v: string | null, locale: string) => string;
  runSummary: (run: ScheduledTaskRun) => string;
  statusLabel: (v: string) => string;
  NONE: string;
}) {
  const stDetail = st.detail;

  return (
    <>
      <DialogHeader>
        <div className="flex items-start justify-between gap-3 pr-8">
          <div className="flex min-w-0 flex-col gap-2">
            <DialogTitle className="leading-snug">
              {editing ? editTitle || task.title : task.title}
            </DialogTitle>
            <StatusBadge status={task.status} statusLabel={statusLabel} />
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditing(!editing)}
          >
            {editing ? st.actions.cancelEdit : st.actions.edit}
          </Button>
        </div>
      </DialogHeader>

      {editing ? (
        <div className="flex flex-col gap-3 py-2">
          <Input
            value={editTitle}
            onChange={(event) => setEditTitle(event.target.value)}
            placeholder={st.edit.titlePlaceholder}
          />
          <Textarea
            rows={4}
            value={editPrompt}
            onChange={(event) => setEditPrompt(event.target.value)}
            placeholder={st.edit.promptPlaceholder}
          />
          <ScheduledTaskScheduleInput
            key={task.id}
            initial={editSchedule}
            onChange={setEditSchedule}
            scheduleTypeLocked
          />
          {editSchedule.schedule_type === "once" &&
            !editSchedule.schedule_spec.run_at && (
              <div className="text-muted-foreground text-sm">
                {st.edit.invalidOnce}
              </div>
            )}
          <Button
            size="sm"
            onClick={() =>
              updateTask.mutate({
                title: editTitle,
                prompt: editPrompt,
                schedule_spec: editSchedule.schedule_spec,
                timezone: editSchedule.timezone || "UTC",
              })
            }
            disabled={
              updateTask.isPending ||
              (!editSchedule.schedule_spec.cron &&
                !editSchedule.schedule_spec.run_at)
            }
          >
            {updateTask.isPending ? t.common.loading : st.edit.submit}
          </Button>
        </div>
      ) : (
        <div className="text-muted-foreground py-2 text-sm leading-relaxed">
          {task.prompt}
        </div>
      )}

      {/* Key-value details */}
      <div className="flex flex-col gap-px py-2">
        {[
          {
            label: stDetail.contextMode,
            value: contextModeLabel(task.context_mode),
          },
          {
            label:
              task.context_mode === "reuse_thread"
                ? stDetail.thread
                : stDetail.lastThread,
            value:
              task.context_mode === "reuse_thread"
                ? (task.thread_id ?? NONE)
                : (task.last_thread_id ?? NONE),
          },
          {
            label: stDetail.schedule,
            value: scheduleTypeLabel(task.schedule_type),
          },
          {
            label: stDetail.nextRun,
            value: formatTimestamp(task.next_run_at, locale),
          },
          {
            label: stDetail.lastRun,
            value: formatTimestamp(task.last_run_at, locale),
          },
          {
            label: stDetail.lastError,
            value: task.last_error ?? NONE,
          },
        ].map((row) => (
          <div
            key={row.label}
            className="flex items-baseline justify-between gap-3 py-1 text-sm"
          >
            <span className="text-muted-foreground shrink-0 text-xs">
              {row.label}
            </span>
            <span className="text-right font-medium tabular-nums">
              {row.value}
            </span>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2 py-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            task.status === "paused"
              ? resumeTask.mutate(task.id)
              : pauseTask.mutate(task.id)
          }
        >
          {task.status === "paused" ? st.actions.resume : st.actions.pause}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => triggerTask.mutate(task.id)}
        >
          {st.actions.trigger}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={() => setDeleteOpen(true)}
        >
          {st.actions.delete}
        </Button>
      </div>

      {/* Run history */}
      <div className="border-t pt-3" data-testid="scheduled-task-runs">
        <div className="text-muted-foreground mb-2 text-xs font-medium">
          {(taskRunsQuery.data ?? []).length === 1
            ? stDetail.runsCountOne.replace(
                "{count}",
                String((taskRunsQuery.data ?? []).length),
              )
            : stDetail.runsCount.replace(
                "{count}",
                String((taskRunsQuery.data ?? []).length),
              )}
        </div>
        <div
          className="flex flex-col gap-1.5"
          data-testid="scheduled-task-run-list"
        >
          {(taskRunsQuery.data ?? []).length > 0 ? (
            (taskRunsQuery.data ?? []).map((run) => (
              <div
                key={run.id}
                className="text-muted-foreground bg-muted/40 rounded-md px-3 py-2 text-xs"
              >
                <div className="text-foreground font-medium">
                  {runSummary(run)}
                </div>
                <div className="mt-0.5 tabular-nums">
                  {formatTimestamp(run.scheduled_for, locale)}
                </div>
                {run.error && (
                  <div className="text-destructive mt-0.5">{run.error}</div>
                )}
              </div>
            ))
          ) : (
            <div className="text-muted-foreground text-sm">
              {stDetail.noRuns}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
