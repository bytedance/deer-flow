export type ScheduledTaskStatus =
  | "enabled"
  | "paused"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

/** Status of an occurrence that is waiting, starting or running right now. */
export type ScheduledTaskActiveRunStatus = "queued" | "launching" | "running";

export type ScheduledTask = {
  id: string;
  thread_id: string | null;
  context_mode: "fresh_thread_per_run" | "reuse_thread";
  assistant_id: string | null;
  title: string;
  /** The user's task instructions exactly as stored; never contains the stop rule. */
  prompt: string;
  schedule_type: "once" | "cron" | "interval";
  schedule_spec: Record<string, unknown>;
  timezone: string;
  status: ScheduledTaskStatus;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_id: string | null;
  last_thread_id: string | null;
  last_error: string | null;
  run_count: number;
  goal_objective?: string | null;
  max_runs?: number | null;
  end_at?: string | null;
  /** The chat that created the task; null for tasks created on the page. */
  origin_thread_id?: string | null;
  standing_notes?: string[] | null;
  /** The user's "stop when …" rule, stored in its own column. */
  stop_condition?: string | null;
  /** Launched scheduled runs counted against `max_runs` (trial runs excluded). */
  automatic_runs_used?: number;
  /**
   * The task's waiting/starting/running occurrence. A recurring task keeps
   * `status: "enabled"` while its occurrence runs, so "is something active?"
   * must read this field too (see `isTaskBusy` / `hasActiveRun`).
   */
  active_run_status?: ScheduledTaskActiveRunStatus | null;
  created_at: string;
  updated_at: string;
};

type ActiveRunFields = Pick<ScheduledTask, "status" | "active_run_status">;

/** A run is starting or running (not merely queued). */
export const isTaskBusy = (task: ActiveRunFields): boolean =>
  task.status === "running" ||
  task.active_run_status === "launching" ||
  task.active_run_status === "running";

/** Any run is queued, starting or running. */
export const hasActiveRun = (task: ActiveRunFields): boolean =>
  task.status === "running" || task.active_run_status != null;

// The verdict an occurrence finished with: from the goal evaluator, or from
// the host when it stood the goal down (see `stand_down_reason`).
export type ScheduledGoalVerdict = {
  satisfied?: boolean;
  blocker?: string;
  relied_on_assumption?: boolean;
  stand_down_reason?: string;
  /** The evaluator's free-text reason; shown only behind "Details". */
  reason?: string;
  /** Extra turns the agent took in this run to reach the goal. */
  continuations?: number;
};

export type ScheduledTaskRun = {
  id: string;
  task_id: string;
  thread_id: string;
  run_id: string | null;
  scheduled_for: string;
  trigger: "scheduled" | "manual";
  status:
    | "queued"
    | "launching"
    | "running"
    | "success"
    | "unmet"
    | "failed"
    | "skipped"
    | "interrupted";
  error: string | null;
  goal_objective?: string | null;
  goal_verdict?: ScheduledGoalVerdict | null;
  stop_requested_run_id?: string | null;
  attempt_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  /** Number of a launched scheduled run, counted like the safety cap; null for trials and never-launched rows. */
  run_number?: number | null;
  total_tokens?: number | null;
  /** First line of the agent's final reply. */
  summary?: string | null;
};

export type ThreadScheduledTask = ScheduledTask & {
  thread_relation: "origin" | "reuse" | "run";
  thread_run: {
    run_number: number | null;
    trigger: "scheduled" | "manual";
    scheduled_for: string;
    status: ScheduledTaskRun["status"];
  } | null;
};

export type ScheduledTaskTriggerResult = {
  id: string;
  triggered: boolean;
  outcome?: "launched" | "queued";
  /** True when a run was already waiting, so no trial was added. */
  existing?: boolean;
  thread_id?: string | null;
};

/** Optional body of a resume: new safety caps; `null` clears that cap. */
export type ScheduledTaskRenewal = {
  max_runs?: number | null;
  end_at?: string | null;
};

/** User-language parts of a scheduled launch, carried on the run's human message. */
export type ScheduledOrigin = {
  task_id: string;
  task_run_id: string;
  trigger: "scheduled" | "manual";
  run_number: number | null;
  scheduled_for: string;
  timezone: string;
  /** Absent on launches recorded before this field existed. */
  schedule_type: ScheduledTask["schedule_type"] | null;
  task_title: string;
  instructions: string;
  stop_condition: string | null;
  standing_notes: string[];
};
