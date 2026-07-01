"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateScheduledTask,
  useUpdateScheduledTask,
  useDeleteScheduledTask,
  usePauseScheduledTask,
  useResumeScheduledTask,
  useScheduledTaskRuns,
  useScheduledTasks,
  useTriggerScheduledTask,
  useThreadScheduledTasks,
} from "@/core/scheduled-tasks/hooks";

export default function ScheduledTasksPage() {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const threadId = searchParams.get("thread_id");
  const allTasksQuery = useScheduledTasks();
  const threadTasksQuery = useThreadScheduledTasks(threadId);
  const data = threadId ? threadTasksQuery.data : allTasksQuery.data;
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [contextMode, setContextMode] = useState<
    "fresh_thread_per_run" | "reuse_thread"
  >(threadId ? "reuse_thread" : "fresh_thread_per_run");
  const [targetThreadId, setTargetThreadId] = useState(threadId ?? "");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [scheduleType, setScheduleType] = useState<"once" | "cron">("cron");
  const [scheduleValue, setScheduleValue] = useState("0 9 * * *");
  const [statusFilter, setStatusFilter] = useState<
    "all" | "enabled" | "paused" | "running" | "completed" | "failed"
  >("all");
  const [typeFilter, setTypeFilter] = useState<"all" | "once" | "cron">("all");
  const [formError, setFormError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [editScheduleValue, setEditScheduleValue] = useState("");
  const selectedTask =
    (data ?? []).find((task) => task.id === selectedTaskId) ?? (data ?? [])[0];
  const filteredData = (data ?? []).filter((task) => {
    const statusPass = statusFilter === "all" || task.status === statusFilter;
    const typePass = typeFilter === "all" || task.schedule_type === typeFilter;
    return statusPass && typePass;
  });
  const taskRunsQuery = useScheduledTaskRuns(selectedTask?.id);
  const createTask = useCreateScheduledTask();
  const updateTask = useUpdateScheduledTask(selectedTask?.id ?? "");
  const pauseTask = usePauseScheduledTask();
  const resumeTask = useResumeScheduledTask();
  const triggerTask = useTriggerScheduledTask();
  const deleteTask = useDeleteScheduledTask();

  useEffect(() => {
    document.title = `${t.sidebar.scheduledTasks} - ${t.pages.appName}`;
  }, [t.pages.appName, t.sidebar.scheduledTasks]);

  useEffect(() => {
    if (!selectedTask) {
      setEditing(false);
      return;
    }
    const cronValue =
      typeof selectedTask.schedule_spec.cron === "string"
        ? selectedTask.schedule_spec.cron
        : "";
    const runAtValue =
      typeof selectedTask.schedule_spec.run_at === "string"
        ? selectedTask.schedule_spec.run_at
        : "";
    setEditTitle(selectedTask.title);
    setEditPrompt(selectedTask.prompt);
    setEditScheduleValue(
      selectedTask.schedule_type === "cron" ? cronValue : runAtValue,
    );
  }, [selectedTask]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-4 p-6">
          <h1 className="text-2xl font-semibold">{t.sidebar.scheduledTasks}</h1>
          <div
            className="grid gap-2 rounded-lg border p-4"
            data-testid="scheduled-task-create-form"
          >
            <div className="font-medium">Create scheduled task</div>
            <div className="flex gap-2">
              <Button
                variant={
                  contextMode === "fresh_thread_per_run" ? "default" : "outline"
                }
                size="sm"
                onClick={() => setContextMode("fresh_thread_per_run")}
              >
                Fresh thread
              </Button>
              <Button
                variant={contextMode === "reuse_thread" ? "default" : "outline"}
                size="sm"
                onClick={() => setContextMode("reuse_thread")}
              >
                Reuse thread
              </Button>
            </div>
            {contextMode === "reuse_thread" && (
              <Input
                value={targetThreadId}
                onChange={(event) => setTargetThreadId(event.target.value)}
                placeholder="Thread ID"
              />
            )}
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Task title"
            />
            <Input
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Prompt"
            />
            <div className="flex gap-2">
              <Button
                variant={scheduleType === "cron" ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  setScheduleType("cron");
                  setScheduleValue("0 9 * * *");
                }}
              >
                Cron
              </Button>
              <Button
                variant={scheduleType === "once" ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  setScheduleType("once");
                  setScheduleValue("2026-07-02T09:00:00+00:00");
                }}
              >
                Once
              </Button>
            </div>
            <Input
              value={scheduleValue}
              onChange={(event) => setScheduleValue(event.target.value)}
              placeholder={
                scheduleType === "cron"
                  ? "Cron expression"
                  : "Run at (ISO datetime)"
              }
            />
            {formError && (
              <div className="text-destructive text-sm">{formError}</div>
            )}
            <Button
              onClick={() => {
                if (
                  !title ||
                  !prompt ||
                  !scheduleValue ||
                  (contextMode === "reuse_thread" && !targetThreadId)
                ) {
                  setFormError("Fill all required fields");
                  return;
                }
                setFormError(null);
                createTask.mutate({
                  context_mode: contextMode,
                  thread_id:
                    contextMode === "reuse_thread" ? targetThreadId : null,
                  title,
                  prompt,
                  schedule_type: scheduleType,
                  schedule_spec:
                    scheduleType === "cron"
                      ? { cron: scheduleValue }
                      : { run_at: scheduleValue },
                  timezone: "UTC",
                });
              }}
              disabled={
                !title ||
                !prompt ||
                !scheduleValue ||
                (contextMode === "reuse_thread" && !targetThreadId) ||
                createTask.isPending
              }
            >
              Create
            </Button>
          </div>
          {threadId && (
            <div className="text-muted-foreground text-sm">
              Filtered by thread: {threadId}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              variant={statusFilter === "all" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("all")}
            >
              All statuses
            </Button>
            <Button
              variant={statusFilter === "enabled" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("enabled")}
            >
              Enabled
            </Button>
            <Button
              variant={statusFilter === "paused" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("paused")}
            >
              Paused
            </Button>
            <Button
              variant={typeFilter === "all" ? "default" : "outline"}
              size="sm"
              onClick={() => setTypeFilter("all")}
            >
              All types
            </Button>
            <Button
              variant={typeFilter === "cron" ? "default" : "outline"}
              size="sm"
              onClick={() => setTypeFilter("cron")}
            >
              Cron
            </Button>
            <Button
              variant={typeFilter === "once" ? "default" : "outline"}
              size="sm"
              onClick={() => setTypeFilter("once")}
            >
              Once
            </Button>
          </div>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
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
                    className={`rounded-lg border p-4 text-left ${
                      isSelected ? "border-foreground" : "border-border"
                    }`}
                  >
                    <div className="font-medium">{task.title}</div>
                    <div className="text-muted-foreground text-sm">
                      {task.schedule_type} · {task.status}
                    </div>
                  </button>
                );
              })}
            </div>
            <div
              className="rounded-lg border p-4"
              data-testid="scheduled-task-detail"
            >
              {selectedTask ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-lg font-semibold">
                      {selectedTask.title}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing((value) => !value)}
                    >
                      {editing ? "Cancel edit" : "Edit"}
                    </Button>
                  </div>
                  <div className="text-muted-foreground text-sm">
                    Context mode: {selectedTask.context_mode}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {selectedTask.context_mode === "reuse_thread"
                      ? `Thread: ${selectedTask.thread_id ?? "None"}`
                      : `Last thread: ${selectedTask.last_thread_id ?? "None"}`}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    Schedule: {selectedTask.schedule_type}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    Next run: {selectedTask.next_run_at ?? "None"}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    Last run: {selectedTask.last_run_at ?? "None"}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    Last run id: {selectedTask.last_run_id ?? "None"}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    Last error: {selectedTask.last_error ?? "None"}
                  </div>
                  {editing ? (
                    <div className="flex flex-col gap-2 rounded-lg border p-3">
                      <Input
                        value={editTitle}
                        onChange={(event) => setEditTitle(event.target.value)}
                        placeholder="Edit title"
                      />
                      <Input
                        value={editPrompt}
                        onChange={(event) => setEditPrompt(event.target.value)}
                        placeholder="Edit prompt"
                      />
                      <Input
                        value={editScheduleValue}
                        onChange={(event) =>
                          setEditScheduleValue(event.target.value)
                        }
                        placeholder="Edit schedule"
                      />
                      <Button
                        size="sm"
                        onClick={() =>
                          updateTask.mutate({
                            title: editTitle,
                            prompt: editPrompt,
                            schedule_spec:
                              selectedTask.schedule_type === "cron"
                                ? { cron: editScheduleValue }
                                : { run_at: editScheduleValue },
                          })
                        }
                        disabled={updateTask.isPending}
                      >
                        Save edit
                      </Button>
                    </div>
                  ) : (
                    <div className="text-sm">{selectedTask.prompt}</div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        selectedTask.status === "paused"
                          ? resumeTask.mutate(selectedTask.id)
                          : pauseTask.mutate(selectedTask.id)
                      }
                    >
                      {selectedTask.status === "paused" ? "Resume" : "Pause"}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => triggerTask.mutate(selectedTask.id)}
                    >
                      Trigger now
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => deleteTask.mutate(selectedTask.id)}
                    >
                      Delete
                    </Button>
                  </div>
                  <div data-testid="scheduled-task-runs">
                    {(taskRunsQuery.data ?? []).length} runs
                  </div>
                  <div
                    className="flex flex-col gap-2"
                    data-testid="scheduled-task-run-list"
                  >
                    {(taskRunsQuery.data ?? []).length > 0 ? (
                      (taskRunsQuery.data ?? []).map((run) => (
                        <div
                          key={run.id}
                          className="rounded-md border p-3 text-sm"
                        >
                          <div className="font-medium">
                            {run.trigger} · {run.status}
                          </div>
                          <div className="text-muted-foreground">
                            Run ID: {run.run_id ?? "None"}
                          </div>
                          <div className="text-muted-foreground">
                            Error: {run.error ?? "None"}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-muted-foreground text-sm">
                        No runs yet
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-muted-foreground text-sm">
                  No scheduled task selected
                </div>
              )}
            </div>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
