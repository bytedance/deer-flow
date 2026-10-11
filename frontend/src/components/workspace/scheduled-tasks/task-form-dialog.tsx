"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, TriangleAlert } from "lucide-react";
import { useId, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { listAgents } from "@/core/agents/api";
import { useAgentsApiEnabled } from "@/core/agents/hooks";
import { useI18n } from "@/core/i18n/hooks";
import type {
  ScheduledTaskPayload,
  ScheduledTaskUpdatePayload,
} from "@/core/scheduled-tasks/api";
import {
  editedZonedLocalToUtcIso,
  hasScheduleSpec,
  onceRunAtInstant,
  parseCron,
  serializeCron,
  utcToZonedLocalInput,
} from "@/core/scheduled-tasks/cron";
import { browserTimeZone } from "@/core/scheduled-tasks/format";
import {
  useCreateScheduledTask,
  useUpdateScheduledTask,
} from "@/core/scheduled-tasks/hooks";
import { RECIPES, type Recipe } from "@/core/scheduled-tasks/recipes";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

import { DEFAULT_ASSISTANT_ID, fill, isFrequentSchedule } from "./shared";

export type TaskFormMode = "create" | "edit" | "duplicate";

export type TaskFormRequest = {
  mode: TaskFormMode;
  /** Source task for edit and duplicate. */
  task?: ScheduledTask;
  /** Field to focus when the dialog opens. */
  focus?: "goal";
};

type ContextMode = ScheduledTask["context_mode"];

export type TaskFormState = {
  title: string;
  prompt: string;
  stopCondition: string;
  goal: string;
  maxRuns: string;
  /** datetime-local wall value in the schedule's timezone; "" = no end time. */
  endAtLocal: string;
  schedule: ScheduleValue;
  assistantId: string;
  contextMode: ContextMode;
  chatId: string;
};

const DEFAULT_SCHEDULE: ScheduleValue = {
  schedule_type: "cron",
  schedule_spec: { cron: "0 9 * * *" },
  timezone: "",
};

function scheduleOf(task: ScheduledTask): ScheduleValue {
  const spec = task.schedule_spec as {
    cron?: unknown;
    run_at?: unknown;
    every_seconds?: unknown;
  };
  return {
    schedule_type: task.schedule_type,
    schedule_spec: {
      cron: typeof spec.cron === "string" ? spec.cron : undefined,
      run_at: typeof spec.run_at === "string" ? spec.run_at : undefined,
      every_seconds:
        typeof spec.every_seconds === "number" ? spec.every_seconds : undefined,
    },
    timezone: task.timezone || browserTimeZone(),
  };
}

/** "Daily report (copy)" / "日报（副本）": a half-width suffix gets a space. */
export function copyTitle(title: string, suffix: string): string {
  return suffix.startsWith("(") ? `${title} ${suffix}` : `${title}${suffix}`;
}

export function initialFormState(
  request: TaskFormRequest,
  copySuffix: string,
  now: Date = new Date(),
): { state: TaskFormState; endAtDropped: boolean } {
  const task = request.task;
  if (!task || request.mode === "create") {
    return {
      state: {
        title: "",
        prompt: "",
        stopCondition: "",
        goal: "",
        maxRuns: "",
        endAtLocal: "",
        schedule: DEFAULT_SCHEDULE,
        assistantId: DEFAULT_ASSISTANT_ID,
        contextMode: "fresh_thread_per_run",
        chatId: "",
      },
      endAtDropped: false,
    };
  }
  const schedule = scheduleOf(task);
  const endAtPassed =
    request.mode === "duplicate" &&
    task.end_at != null &&
    Date.parse(task.end_at) <= now.getTime();
  return {
    state: {
      title:
        request.mode === "duplicate"
          ? copyTitle(task.title, copySuffix)
          : task.title,
      prompt: task.prompt,
      stopCondition: task.stop_condition ?? "",
      goal: task.goal_objective ?? "",
      maxRuns: task.max_runs != null ? String(task.max_runs) : "",
      endAtLocal:
        task.end_at && !endAtPassed
          ? utcToZonedLocalInput(task.end_at, schedule.timezone)
          : "",
      schedule,
      assistantId: task.assistant_id ?? DEFAULT_ASSISTANT_ID,
      contextMode: task.context_mode,
      chatId: task.thread_id ?? "",
    },
    endAtDropped: endAtPassed,
  };
}

function sameSchedule(task: ScheduledTask, value: ScheduleValue): boolean {
  if (task.schedule_type !== value.schedule_type) return false;
  if ((task.timezone || "UTC") !== (value.timezone || "UTC")) return false;
  const spec = task.schedule_spec;
  const next = value.schedule_spec;
  switch (value.schedule_type) {
    case "once":
      return (
        typeof spec.run_at === "string" &&
        typeof next.run_at === "string" &&
        Date.parse(onceRunAtInstant(spec.run_at, task.timezone || "UTC")) ===
          Date.parse(onceRunAtInstant(next.run_at, value.timezone || "UTC"))
      );
    case "interval":
      return spec.every_seconds === next.every_seconds;
    case "cron": {
      // The schedule input re-serializes a cron it shows as a preset
      // ("0 09 * * 0,6" -> "0 9 * * 6,0"); compare that form, so an untouched
      // schedule is never re-sent and never re-arms a finished task.
      const canonical = (cron: unknown) => {
        if (typeof cron !== "string") return "";
        const { preset, parts } = parseCron(cron);
        return serializeCron(preset, parts).split(/\s+/).join(" ");
      };
      return canonical(spec.cron) === canonical(next.cron);
    }
  }
}

function normalizeText(value: string): string | null {
  const text = value.trim();
  return text ? text : null;
}

export type FormValidation =
  | { ok: true; maxRuns: number | null; endAt: string | null }
  | {
      ok: false;
      error: "required" | "invalidMaxRuns" | "invalidEndAt" | "goalNeedsFresh";
    };

/**
 * `storedEndAt` is the source task's end time (edit and duplicate): kept
 * as is while the end-time field still shows it.
 */
export function validateForm(
  state: TaskFormState,
  storedEndAt?: string | null,
): FormValidation {
  if (
    !state.title.trim() ||
    !state.prompt.trim() ||
    !hasScheduleSpec(state.schedule.schedule_spec) ||
    (state.contextMode === "reuse_thread" && !state.chatId.trim())
  ) {
    return { ok: false, error: "required" };
  }
  let maxRuns: number | null = null;
  if (state.maxRuns.trim() !== "") {
    const value = Number(state.maxRuns);
    if (!Number.isInteger(value) || value < 1) {
      return { ok: false, error: "invalidMaxRuns" };
    }
    maxRuns = value;
  }
  let endAt: string | null = null;
  if (state.endAtLocal) {
    endAt = editedZonedLocalToUtcIso(
      state.endAtLocal,
      state.schedule.timezone || browserTimeZone(),
      storedEndAt,
    );
    if (!endAt) {
      return { ok: false, error: "invalidEndAt" };
    }
  }
  if (state.contextMode === "reuse_thread" && normalizeText(state.goal)) {
    return { ok: false, error: "goalNeedsFresh" };
  }
  return { ok: true, maxRuns, endAt };
}

/** Full create body (also used by Duplicate). */
export function createPayload(
  state: TaskFormState,
  valid: { maxRuns: number | null; endAt: string | null },
): ScheduledTaskPayload {
  const reuse = state.contextMode === "reuse_thread";
  const payload: ScheduledTaskPayload = {
    context_mode: state.contextMode,
    thread_id: reuse ? state.chatId.trim() : null,
    assistant_id: state.assistantId,
    title: state.title.trim(),
    prompt: state.prompt,
    schedule_type: state.schedule.schedule_type,
    schedule_spec: state.schedule.schedule_spec,
    timezone: state.schedule.timezone || "UTC",
  };
  const goal = reuse ? null : normalizeText(state.goal);
  if (goal) payload.goal_objective = goal;
  if (valid.maxRuns != null) payload.max_runs = valid.maxRuns;
  if (valid.endAt) payload.end_at = valid.endAt;
  const stop = normalizeText(state.stopCondition);
  if (stop) payload.stop_condition = stop;
  return payload;
}

/**
 * PATCH body: only what changed. Clearing the goal, stop condition, run limit
 * or end time sends `null`; the schedule is sent (with its timezone) only
 * when it changed, so an untouched one-time instant is never re-submitted.
 */
export function updatePayload(
  task: ScheduledTask,
  state: TaskFormState,
  valid: { maxRuns: number | null; endAt: string | null },
  { includeStopCondition }: { includeStopCondition: boolean },
): ScheduledTaskUpdatePayload {
  const updates: ScheduledTaskUpdatePayload = {};
  const title = state.title.trim();
  if (title !== task.title) updates.title = title;
  if (state.prompt !== task.prompt) updates.prompt = state.prompt;
  if (!sameSchedule(task, state.schedule)) {
    updates.schedule_spec = state.schedule.schedule_spec;
    updates.timezone = state.schedule.timezone || "UTC";
  }
  if (state.assistantId !== (task.assistant_id ?? DEFAULT_ASSISTANT_ID)) {
    updates.assistant_id = state.assistantId;
  }
  const reuse = state.contextMode === "reuse_thread";
  if (state.contextMode !== task.context_mode) {
    updates.context_mode = state.contextMode;
    updates.thread_id = reuse ? state.chatId.trim() : null;
  } else if (reuse && state.chatId.trim() !== (task.thread_id ?? "")) {
    updates.thread_id = state.chatId.trim();
  }
  const goal = reuse ? null : normalizeText(state.goal);
  if (goal !== (task.goal_objective ?? null)) updates.goal_objective = goal;
  if (includeStopCondition) {
    const stop = normalizeText(state.stopCondition);
    if (stop !== (task.stop_condition ?? null)) updates.stop_condition = stop;
  }
  if (valid.maxRuns !== (task.max_runs ?? null)) {
    updates.max_runs = valid.maxRuns;
  }
  // The input has minute precision: an untouched end time with seconds must
  // not count as a change.
  const minute = (iso: string) => Math.floor(Date.parse(iso) / 60_000);
  const endChanged =
    valid.endAt === null
      ? task.end_at != null
      : !task.end_at || minute(valid.endAt) !== minute(task.end_at);
  if (endChanged) updates.end_at = valid.endAt;
  return updates;
}

export function TaskFormDialog({
  request,
  toolEnabled,
  minIntervalSeconds,
  onOpenChange,
  onSaved,
}: {
  request: TaskFormRequest | null;
  toolEnabled: boolean;
  /** Server floor for interval schedules (`/api/features`). */
  minIntervalSeconds?: number;
  onOpenChange: (open: boolean) => void;
  onSaved?: (task: ScheduledTask, mode: TaskFormMode) => void;
}) {
  return (
    <Dialog open={request !== null} onOpenChange={onOpenChange}>
      {request && (
        <TaskForm
          key={`${request.mode}:${request.task?.id ?? ""}`}
          request={request}
          toolEnabled={toolEnabled}
          minIntervalSeconds={minIntervalSeconds}
          onClose={() => onOpenChange(false)}
          onSaved={onSaved}
        />
      )}
    </Dialog>
  );
}

function TaskForm({
  request,
  toolEnabled,
  minIntervalSeconds,
  onClose,
  onSaved,
}: {
  request: TaskFormRequest;
  toolEnabled: boolean;
  minIntervalSeconds?: number;
  onClose: () => void;
  onSaved?: (task: ScheduledTask, mode: TaskFormMode) => void;
}) {
  const { t } = useI18n();
  const st = t.scheduledTasks;
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const { mode, task } = request;
  const editing = mode === "edit" && task !== undefined;
  const [initial] = useState(() =>
    initialFormState(request, st.form.copySuffix),
  );
  const [state, setState] = useState<TaskFormState>(initial.state);
  const [scheduleNonce, setScheduleNonce] = useState(0);
  const [scheduleInitial, setScheduleInitial] = useState(
    initial.state.schedule,
  );
  const [error, setError] = useState<string | null>(null);
  const goalRef = useRef<HTMLTextAreaElement>(null);
  const set = <K extends keyof TaskFormState>(
    key: K,
    value: TaskFormState[K],
  ) => setState((prev) => ({ ...prev, [key]: value }));

  const { enabled: agentsApiEnabled, isLoading: agentsApiLoading } =
    useAgentsApiEnabled();
  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: listAgents,
    enabled: !agentsApiLoading && agentsApiEnabled,
    retry: false,
  });
  const agentOptions = useMemo(() => {
    const options = [
      { value: DEFAULT_ASSISTANT_ID, label: st.create.leadAgent },
      ...(agentsQuery.data ?? [])
        .filter((agent) => agent.name !== DEFAULT_ASSISTANT_ID)
        .map((agent) => ({ value: agent.name, label: agent.name })),
    ];
    if (!options.some((option) => option.value === state.assistantId)) {
      options.push({ value: state.assistantId, label: state.assistantId });
    }
    return options;
  }, [agentsQuery.data, state.assistantId, st.create.leadAgent]);

  const createTask = useCreateScheduledTask();
  const updateTask = useUpdateScheduledTask(task?.id ?? "");
  const pending = createTask.isPending || updateTask.isPending;
  const reuse = state.contextMode === "reuse_thread";
  // A duplicate or a new task has used no runs yet, whatever its source did.
  const used = editing ? (task.automatic_runs_used ?? 0) : 0;
  const showFrequentWarning =
    editing &&
    task.origin_thread_id != null &&
    isFrequentSchedule(
      state.schedule.schedule_type,
      state.schedule.schedule_spec,
    ) &&
    !state.maxRuns.trim() &&
    !state.endAtLocal;
  const [advancedOpen, setAdvancedOpen] = useState(
    reuse || state.assistantId !== DEFAULT_ASSISTANT_ID,
  );
  const timeZone = state.schedule.timezone || browserTimeZone();

  const applyRecipe = (recipe: Recipe) => {
    const labels = st.recipes[recipe.titleKey];
    setState((prev) => ({
      ...prev,
      title: labels.title,
      prompt: labels.prompt,
      schedule: recipe.schedule,
      contextMode: "fresh_thread_per_run",
    }));
    setScheduleInitial(recipe.schedule);
    setScheduleNonce((nonce) => nonce + 1);
  };

  const submit = () => {
    const valid = validateForm(state, task?.end_at);
    if (!valid.ok) {
      setError(
        valid.error === "required"
          ? st.form.required
          : valid.error === "invalidMaxRuns"
            ? st.apiErrors.invalidMaxRuns
            : valid.error === "goalNeedsFresh"
              ? st.form.goalNeedsFresh
              : st.form.invalidEndAt,
      );
      return;
    }
    setError(null);
    if (editing) {
      // Edit sends the stop condition only while its field is shown; a hidden
      // field is left untouched on the server.
      const updates = updatePayload(task, state, valid, {
        includeStopCondition: toolEnabled,
      });
      if (Object.keys(updates).length === 0) {
        onClose();
        return;
      }
      updateTask.mutate(updates, {
        onSuccess: (saved) => {
          toast.success(st.feedback.saved);
          onClose();
          onSaved?.(saved, mode);
        },
      });
      return;
    }
    // Create and Duplicate always send it: a duplicate copies the source's
    // stop condition even while the field is hidden (the run is then told
    // the condition without being given the tool, spec 3.4).
    createTask.mutate(createPayload(state, valid), {
      onSuccess: (created) => {
        toast.success(st.feedback.created);
        onClose();
        onSaved?.(created, mode);
      },
    });
  };

  return (
    <DialogContent
      className="max-h-[90vh] overflow-y-auto sm:max-w-xl"
      data-testid="scheduled-task-form"
      onOpenAutoFocus={(event) => {
        if (request.focus === "goal" && goalRef.current) {
          event.preventDefault();
          goalRef.current.focus();
        }
      }}
    >
      <DialogHeader>
        <DialogTitle>
          {editing ? st.form.editTitle : st.form.createTitle}
        </DialogTitle>
        <DialogDescription className="sr-only">
          {st.form.instructionsHint}
        </DialogDescription>
      </DialogHeader>
      {/* Not a <form>: the schedule input's toggle buttons have no type. */}
      <div className="flex min-w-0 flex-col gap-4">
        {mode === "create" && (
          <div
            className="flex flex-wrap items-center gap-1"
            data-testid="schedule-recipes"
          >
            <span className="text-muted-foreground text-sm">
              {st.recipes.label}
            </span>
            {RECIPES.map((recipe) => (
              <Button
                key={recipe.id}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => applyRecipe(recipe)}
              >
                <span aria-hidden>{recipe.icon}</span>
                {st.recipes[recipe.titleKey].title}
              </Button>
            ))}
          </div>
        )}

        <Field id={id("title")} label={st.form.title}>
          <Input
            id={id("title")}
            value={state.title}
            autoFocus={request.focus !== "goal"}
            onChange={(event) => set("title", event.target.value)}
          />
        </Field>

        <Field
          id={id("prompt")}
          label={st.form.instructions}
          hint={st.form.instructionsHint}
        >
          <Textarea
            id={id("prompt")}
            rows={4}
            value={state.prompt}
            aria-describedby={`${id("prompt")}-hint`}
            onChange={(event) => set("prompt", event.target.value)}
          />
        </Field>

        <fieldset className="flex min-w-0 flex-col gap-1.5">
          <legend className="mb-1.5 text-sm font-medium">
            {st.form.schedule}
          </legend>
          <ScheduledTaskScheduleInput
            key={scheduleNonce}
            initial={scheduleInitial}
            onChange={(value) => set("schedule", value)}
            scheduleTypeLocked={editing}
            minIntervalSeconds={minIntervalSeconds}
          />
        </fieldset>

        {toolEnabled && (
          <Field
            id={id("stop")}
            label={st.form.stopCondition}
            hint={st.form.stopConditionHint}
          >
            <Textarea
              id={id("stop")}
              rows={2}
              value={state.stopCondition}
              aria-describedby={`${id("stop")}-hint`}
              onChange={(event) => set("stopCondition", event.target.value)}
            />
          </Field>
        )}

        <Field
          id={id("goal")}
          label={st.form.goal}
          hint={reuse ? st.form.goalNeedsFresh : st.form.goalHint}
        >
          <Textarea
            id={id("goal")}
            ref={goalRef}
            rows={2}
            value={state.goal}
            // In an existing chat a goal can't be saved; keep the field
            // editable while it still holds text so the user can clear it.
            disabled={reuse && !state.goal}
            aria-describedby={`${id("goal")}-hint`}
            onChange={(event) => set("goal", event.target.value)}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id={id("max-runs")}
            label={st.form.maxRuns}
            hint={fill(st.form.maxRunsHint, { used })}
          >
            <div className="flex gap-2">
              <Input
                id={id("max-runs")}
                type="number"
                inputMode="numeric"
                min={1}
                value={state.maxRuns}
                aria-describedby={`${id("max-runs")}-hint`}
                onChange={(event) => set("maxRuns", event.target.value)}
              />
              {state.maxRuns && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`${st.form.clear} ${st.form.maxRuns}`}
                  onClick={() => set("maxRuns", "")}
                >
                  {st.form.clear}
                </Button>
              )}
            </div>
          </Field>
          <Field
            id={id("end-at")}
            label={fill(st.form.labelWithZone, {
              label: st.form.endAt,
              tz: timeZone,
            })}
            hint={initial.endAtDropped ? st.form.endAtPassed : undefined}
          >
            <div className="flex gap-2">
              <Input
                id={id("end-at")}
                type="datetime-local"
                value={state.endAtLocal}
                aria-describedby={
                  initial.endAtDropped ? `${id("end-at")}-hint` : undefined
                }
                onChange={(event) => set("endAtLocal", event.target.value)}
              />
              {state.endAtLocal && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`${st.form.clear} ${st.form.endAt}`}
                  onClick={() => set("endAtLocal", "")}
                >
                  {st.form.clear}
                </Button>
              )}
            </div>
          </Field>
        </div>
        {showFrequentWarning && (
          <p
            role="note"
            className="flex items-center gap-1.5 text-sm text-amber-700 dark:text-amber-400"
          >
            <TriangleAlert className="size-4 shrink-0" aria-hidden />
            {st.form.frequentNeedsCap}
          </p>
        )}

        <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
          <CollapsibleTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="-ml-2 w-fit"
            >
              <ChevronDown
                className={cn(
                  "size-4 transition-transform",
                  !advancedOpen && "-rotate-90",
                )}
                aria-hidden
              />
              {st.form.advanced}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 flex flex-col gap-4">
            <Field id={id("agent")} label={st.form.agent}>
              <Select
                value={state.assistantId}
                onValueChange={(value) => set("assistantId", value)}
              >
                <SelectTrigger
                  id={id("agent")}
                  className="w-full"
                  data-testid="scheduled-task-form-agent"
                  aria-label={st.form.agent}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {agentOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <div
              className="flex flex-wrap gap-2"
              role="group"
              aria-label={st.form.contextLabel}
            >
              <Button
                type="button"
                size="sm"
                variant={reuse ? "outline" : "default"}
                aria-pressed={!reuse}
                onClick={() => set("contextMode", "fresh_thread_per_run")}
              >
                {st.form.contextFresh}
              </Button>
              <Button
                type="button"
                size="sm"
                variant={reuse ? "default" : "outline"}
                aria-pressed={reuse}
                onClick={() => set("contextMode", "reuse_thread")}
              >
                {st.form.contextReuse}
              </Button>
            </div>
            {reuse && (
              <>
                <Field id={id("chat")} label={st.form.chatId}>
                  <Input
                    id={id("chat")}
                    value={state.chatId}
                    onChange={(event) => set("chatId", event.target.value)}
                  />
                </Field>
                <Alert className="border-amber-500/50 bg-amber-500/10">
                  <TriangleAlert className="text-amber-600 dark:text-amber-400" />
                  <AlertTitle>{st.form.reuseNoticeTitle}</AlertTitle>
                  <AlertDescription>
                    {st.form.reuseNoticeDescription}
                  </AlertDescription>
                </Alert>
              </>
            )}
          </CollapsibleContent>
        </Collapsible>

        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={pending}
          >
            {t.common.cancel}
          </Button>
          <Button
            type="button"
            onClick={submit}
            disabled={pending || !hasScheduleSpec(state.schedule.schedule_spec)}
          >
            {editing ? st.form.save : st.form.create}
          </Button>
        </DialogFooter>
      </div>
    </DialogContent>
  );
}

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="text-muted-foreground text-xs">
          {hint}
        </p>
      )}
    </div>
  );
}
