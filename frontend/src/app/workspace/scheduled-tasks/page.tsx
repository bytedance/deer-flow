"use client";

import { CalendarClock, Plus } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
  // Use a locale-aware short format like "2026-07-03 09:00". Future timestamps
  // (next_run_at) render as an absolute time, not a relative "ago" string.
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

function StatusBadge({ status }: { status: string }) {
  const dot = STATUS_DOT[status] ?? "bg-zinc-400";
  return (
    <span className="text-muted-foreground inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-xs font-medium">
      <span aria-hidden className={cn("size-1.5 rounded-full", dot)} />
      {status}
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
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
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
    filteredData.find((task) => task.id === selectedTaskId) ?? filteredData[0];
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
      setSelectedTaskId(filteredData[0]?.id ?? null);
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
    // Depend on id only so a background refetch (same task, new object reference)
    // does not wipe edits in progress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTask?.id]);

  const statusFilters = [
    { id: "enabled" as const, label: st.filters.enabled },
    { id: "paused" as const, label: st.filters.paused },
  ];

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
          onClick={() => router.push("/workspace/scheduled-tasks/new")}
          data-testid="scheduled-task-create-toggle"
        >
          <Plus className="mr-1.5 h-4 w-4" />
          {st.create.title}
        </Button>
      </header>
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-5 p-6">
          {threadId && (
            <div className="text-muted-foreground text-sm">
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
            <div className="flex flex-wrap items-center gap-2">
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
          {filteredData.length === 0 ? (
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
                onClick={() => router.push("/workspace/scheduled-tasks/new")}
              >
                <Plus className="mr-1.5 h-4 w-4" />
                {st.create.title}
              </Button>
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
              <div
                data-testid="scheduled-task-list"
                className="flex flex-col gap-3"
              >
                {filteredData.map((task) => {
                  const isSelected = selectedTask?.id === task.id;
                  return (
                    <button
                      type="button"
                      key={task.id}
                      onClick={() => setSelectedTaskId(task.id)}
                      data-testid={`scheduled-task-item-${task.id}`}
                      className={cn(
                        "bg-card flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors",
                        isSelected
                          ? "border-foreground bg-card ring-foreground/10 ring-1"
                          : "border-border hover:bg-secondary/40",
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium">
                          {task.title}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={statusLabel(task.status)} />
                        <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
                          {scheduleTypeLabel(task.schedule_type)}
                        </span>
                        <span className="text-muted-foreground ml-auto inline-flex items-center gap-1 text-xs tabular-nums">
                          <CalendarClock className="size-3.5" />
                          {formatTimestamp(task.next_run_at, locale)}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
              {selectedTask ? (
                <div
                  className="bg-card rounded-xl border p-5"
                  data-testid="scheduled-task-detail"
                >
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
                </div>
              ) : null}
            </div>
          )}
        </div>
      </WorkspaceBody>

      {/* Delete confirm — follows the agent-card confirm pattern. */}
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
                    onSuccess: () => setDeleteOpen(false),
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
  const rows: Array<{ label: string; value: string }> = [
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
    { label: stDetail.schedule, value: scheduleTypeLabel(task.schedule_type) },
    {
      label: stDetail.nextRun,
      value: formatTimestamp(task.next_run_at, locale),
    },
    {
      label: stDetail.lastRun,
      value: formatTimestamp(task.last_run_at, locale),
    },
    { label: stDetail.lastRunId, value: task.last_run_id ?? NONE },
    ...(task.last_error
      ? [{ label: stDetail.lastError, value: task.last_error }]
      : []),
  ];

  return (
    <Card className="gap-4 border-0 bg-transparent py-0 shadow-none">
      <CardContent className="flex flex-col gap-5 px-0">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-2">
            <div className="text-base leading-snug font-semibold">
              {task.title}
            </div>
            <StatusBadge status={statusLabel(task.status)} />
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditing(!editing)}
          >
            {editing ? st.actions.cancelEdit : st.actions.edit}
          </Button>
        </div>

        {editing ? (
          <div className="flex flex-col gap-3 rounded-lg border p-3">
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
              disabled={updateTask.isPending}
            >
              {updateTask.isPending ? t.common.loading : st.edit.submit}
            </Button>
          </div>
        ) : (
          <div className="text-sm leading-relaxed">{task.prompt}</div>
        )}

        <div className="bg-border grid gap-px overflow-hidden rounded-lg border">
          {rows.map((row) => (
            <div
              key={row.label}
              className="bg-card grid grid-cols-[120px_minmax(0,1fr)] items-center gap-3 px-3 py-2 text-sm"
            >
              <span className="text-muted-foreground text-xs">{row.label}</span>
              <span className="truncate font-medium tabular-nums">
                {row.value}
              </span>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
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

        <div>
          <div
            className="text-muted-foreground mb-2 text-xs font-medium"
            data-testid="scheduled-task-runs"
          >
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
            className="flex flex-col gap-2"
            data-testid="scheduled-task-run-list"
          >
            {(taskRunsQuery.data ?? []).length > 0 ? (
              (taskRunsQuery.data ?? []).map((run) => (
                <div key={run.id} className="rounded-md border p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{runSummary(run)}</span>
                  </div>
                  <div className="text-muted-foreground text-xs">
                    {run.run_id ?? NONE}
                  </div>
                  <div className="text-muted-foreground text-xs tabular-nums">
                    {formatTimestamp(run.scheduled_for, locale)}
                  </div>
                  {run.error && (
                    <div className="text-destructive text-xs">{run.error}</div>
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
      </CardContent>
    </Card>
  );
}
