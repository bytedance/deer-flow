"use client";

import { ArrowLeftIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { useI18n } from "@/core/i18n/hooks";
import { useCreateScheduledTask } from "@/core/scheduled-tasks/hooks";

export default function NewScheduledTaskPage() {
  const { t } = useI18n();
  const router = useRouter();
  const st = t.scheduledTasks;
  const createTask = useCreateScheduledTask();
  const [contextMode, setContextMode] = useState<
    "fresh_thread_per_run" | "reuse_thread"
  >("fresh_thread_per_run");
  const [targetThreadId, setTargetThreadId] = useState("");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [createSchedule, setCreateSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "",
  });
  const [formError, setFormError] = useState<string | null>(null);

  const handleCreate = () => {
    const hasSchedule =
      Boolean(createSchedule.schedule_spec.cron) ||
      Boolean(createSchedule.schedule_spec.run_at);
    if (
      !title ||
      !prompt ||
      !hasSchedule ||
      (contextMode === "reuse_thread" && !targetThreadId)
    ) {
      setFormError(st.create.fillRequired);
      return;
    }
    setFormError(null);
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
      { onSuccess: () => router.push("/workspace/scheduled-tasks") },
    );
  };

  return (
    <div className="flex size-full flex-col">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => router.push("/workspace/scheduled-tasks")}
          >
            <ArrowLeftIcon className="h-4 w-4" />
          </Button>
          <h1 className="text-sm font-semibold">{st.create.title}</h1>
        </div>
      </header>
      <main className="flex flex-1 justify-center overflow-y-auto px-4 py-6">
        <div className="w-full max-w-xl space-y-4">
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
            <Input
              value={targetThreadId}
              onChange={(event) => setTargetThreadId(event.target.value)}
              placeholder={st.context.threadIdPlaceholder}
            />
          )}
          <Input
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
            initial={createSchedule}
            onChange={setCreateSchedule}
          />
          {formError && (
            <div className="text-destructive text-sm">{formError}</div>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => router.push("/workspace/scheduled-tasks")}
              disabled={createTask.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={handleCreate}
              disabled={
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
