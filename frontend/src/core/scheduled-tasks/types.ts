export type ScheduledTask = {
  id: string;
  thread_id: string | null;
  context_mode: "fresh_thread_per_run" | "reuse_thread";
  assistant_id: string | null;
  title: string;
  prompt: string;
  schedule_type: "once" | "cron" | "interval";
  schedule_spec: Record<string, unknown>;
  timezone: string;
  status:
    | "enabled"
    | "paused"
    | "running"
    | "completed"
    | "failed"
    | "cancelled";
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_id: string | null;
  last_thread_id: string | null;
  last_error: string | null;
  run_count: number;
  // Only conversation-created tasks set these; other tasks omit them or send null.
  goal_objective?: string | null;
  max_runs?: number | null;
  end_at?: string | null;
  created_at: string;
  updated_at: string;
};

// The verdict an occurrence finished with: from the goal evaluator, or from
// the host when it stood the goal down (see `stand_down_reason`).
export type ScheduledGoalVerdict = {
  satisfied?: boolean;
  blocker?: string;
  relied_on_assumption?: boolean;
  stand_down_reason?: string;
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
};
