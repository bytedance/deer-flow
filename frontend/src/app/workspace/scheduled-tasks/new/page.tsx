"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeftIcon, CalendarClock, TriangleAlertIcon } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { useI18n } from "@/core/i18n/hooks";
import { fetchScheduledTasks } from "@/core/scheduled-tasks/api";
import {
  clearDuplicateDraft,
  draftFromScheduledTask,
  getSessionDuplicateDraftStorage,
  readDuplicateDraft,
  resolveCreateContextMode,
  type DuplicateDraft,
} from "@/core/scheduled-tasks/duplicate-draft";
import { useCreateScheduledTask } from "@/core/scheduled-tasks/hooks";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

function ReuseThreadNotice({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Alert className="border-amber-500/50 bg-amber-500/10">
      <TriangleAlertIcon className="text-amber-600 dark:text-amber-400" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{description}</AlertDescription>
    </Alert>
  );
}

function scheduleFromDraft(draft: DuplicateDraft): ScheduleValue {
  const spec = draft.schedule_spec as { cron?: string; run_at?: string };
  if (draft.schedule_type === "once") {
    return {
      schedule_type: "once",
      schedule_spec: spec.run_at ? { run_at: spec.run_at } : {},
      timezone: draft.timezone ?? "",
    };
  }
  return {
    schedule_type: "cron",
    schedule_spec: { cron: spec.cron ?? "0 9 * * *" },
    timezone: draft.timezone ?? "",
  };
}

export default function NewScheduledTaskPage() {
  const { t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const sourceTaskId = searchParams.get("from");
  const initialThreadId = searchParams.get("thread_id");
  const initialContextMode = searchParams.get("context_mode");
  const st = t.scheduledTasks;
  const createTask = useCreateScheduledTask();
  const [contextMode, setContextMode] = useState<
    "fresh_thread_per_run" | "reuse_thread"
  >(() =>
    resolveCreateContextMode({
      contextModeParam: initialContextMode,
      threadIdParam: sourceTaskId ? null : initialThreadId,
    }),
  );
  const [targetThreadId, setTargetThreadId] = useState(
    sourceTaskId ? "" : (initialThreadId ?? ""),
  );
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [createSchedule, setCreateSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "",
  });
  const [sourceStatus, setSourceStatus] = useState<
    "idle" | "loading" | "ready" | "missing"
  >(sourceTaskId ? "loading" : "idle");

  const applyDraft = (draft: DuplicateDraft) => {
    setTitle(draft.title);
    setPrompt(draft.prompt);
    setContextMode(draft.context_mode);
    setTargetThreadId(draft.thread_id ?? "");
    setCreateSchedule(scheduleFromDraft(draft));
    setSourceStatus("ready");
  };

  useEffect(() => {
    if (!sourceTaskId) {
      return;
    }
    let cancelled = false;
    const applyIfCurrent = (draft: DuplicateDraft) => {
      if (!cancelled) {
        applyDraft(draft);
      }
    };

    const sessionDraft = readDuplicateDraft(
      getSessionDuplicateDraftStorage(),
      sourceTaskId,
    );
    if (sessionDraft) {
      applyIfCurrent(sessionDraft);
      clearDuplicateDraft(getSessionDuplicateDraftStorage(), sourceTaskId);
      return () => {
        cancelled = true;
      };
    }

    const cached = queryClient
      .getQueryData<ScheduledTask[]>(["scheduled-tasks"])
      ?.find((task) => task.id === sourceTaskId);
    if (cached) {
      applyIfCurrent(
        draftFromScheduledTask(cached, st.actions.duplicateTitleSuffix),
      );
      return () => {
        cancelled = true;
      };
    }

    void fetchScheduledTasks()
      .then((tasks) => {
        const found = tasks.find((task) => task.id === sourceTaskId);
        if (!found) {
          if (!cancelled) {
            setSourceStatus("missing");
          }
          return;
        }
        applyIfCurrent(
          draftFromScheduledTask(found, st.actions.duplicateTitleSuffix),
        );
      })
      .catch(() => {
        if (!cancelled) {
          setSourceStatus("missing");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [queryClient, sourceTaskId, st.actions.duplicateTitleSuffix]);

  const listHref = initialThreadId
    ? `/workspace/scheduled-tasks?thread_id=${encodeURIComponent(initialThreadId)}`
    : "/workspace/scheduled-tasks";

  const successHref =
    contextMode === "reuse_thread" && targetThreadId
      ? `/workspace/scheduled-tasks?thread_id=${encodeURIComponent(targetThreadId)}`
      : "/workspace/scheduled-tasks";

  const handleCreate = () => {
    createTask.mutate(
      {
        context_mode: contextMode,
        thread_id: contextMode === "reuse_thread" ? targetThreadId : null,
        title,
        prompt,
        schedule_type: createSchedule.schedule_type,
        schedule_spec: createSchedule.schedule_spec,
        timezone: createSchedule.timezone || "UTC",
      },
      { onSuccess: () => router.push(successHref) },
    );
  };

  return (
    <div className="flex size-full flex-col">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={st.create.back}
            title={st.create.back}
            onClick={() => router.push(listHref)}
          >
            <ArrowLeftIcon className="h-4 w-4" />
          </Button>
          <h1 className="text-sm font-semibold">{st.create.title}</h1>
        </div>
      </header>
      <main className="flex flex-1 justify-center overflow-y-auto px-4 py-6">
        <div
          className="my-auto w-full max-w-xl space-y-4"
          data-testid="scheduled-task-create-form"
        >
          <div className="space-y-3 pb-2 text-center">
            <div className="bg-primary/10 mx-auto flex h-14 w-14 items-center justify-center rounded-full">
              <CalendarClock className="text-primary h-7 w-7" />
            </div>
            <div className="space-y-1">
              <h2 className="text-xl font-semibold">{st.create.title}</h2>
              <p className="text-muted-foreground text-sm">{st.description}</p>
            </div>
          </div>
          {sourceStatus === "missing" && (
            <div className="text-destructive text-sm">
              {st.create.sourceMissing}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant={
                contextMode === "fresh_thread_per_run" ? "default" : "outline"
              }
              size="sm"
              onClick={() => setContextMode("fresh_thread_per_run")}
            >
              {st.context.fresh}
            </Button>
            <Button
              type="button"
              variant={contextMode === "reuse_thread" ? "default" : "outline"}
              size="sm"
              onClick={() => setContextMode("reuse_thread")}
            >
              {st.context.reuse}
            </Button>
          </div>
          {contextMode === "reuse_thread" && (
            <>
              <Input
                value={targetThreadId}
                onChange={(event) => setTargetThreadId(event.target.value)}
                placeholder={st.context.threadIdPlaceholder}
              />
              <ReuseThreadNotice
                title={st.context.reuseNoticeTitle}
                description={st.context.reuseNoticeDescription}
              />
            </>
          )}
          <Input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={st.create.taskTitle}
          />
          <Textarea
            rows={4}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={st.create.prompt}
          />
          <ScheduledTaskScheduleInput
            key={
              sourceTaskId
                ? `${sourceTaskId}:${createSchedule.schedule_type}:${JSON.stringify(createSchedule.schedule_spec)}`
                : "new"
            }
            initial={createSchedule}
            onChange={setCreateSchedule}
          />
          {createSchedule.schedule_type === "once" &&
            !createSchedule.schedule_spec.run_at && (
              <div className="text-muted-foreground text-sm">
                {st.create.invalidOnce}
              </div>
            )}
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => router.push(listHref)}
              disabled={createTask.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={handleCreate}
              disabled={
                sourceStatus === "loading" ||
                sourceStatus === "missing" ||
                !title ||
                !prompt ||
                (!createSchedule.schedule_spec.cron &&
                  !createSchedule.schedule_spec.run_at) ||
                (contextMode === "reuse_thread" && !targetThreadId) ||
                createTask.isPending
              }
            >
              {createTask.isPending ? t.common.loading : st.create.submit}
            </Button>
          </div>
        </div>
      </main>
    </div>
  );
}
