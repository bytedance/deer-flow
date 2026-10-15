export type SubagentBatchStatus =
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type SubagentBatchItemStatus =
  | "pending"
  | "queued"
  | "leased"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export type SubagentBatchCounts = Record<SubagentBatchItemStatus, number>;

export type SubagentBatch = {
  id: string;
  title: string;
  subagent_type: string;
  status: SubagentBatchStatus;
  total_items: number;
  max_live_items: number;
  max_running_items: number;
  max_attempts: number;
  counts: SubagentBatchCounts;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type SubagentBatchItem = {
  id: string;
  batch_id: string;
  item_key: string;
  position: number;
  status: SubagentBatchItemStatus;
  attempt: number;
  model_name: string | null;
  result_preview: string | null;
  result_truncated: boolean;
  error: string | null;
  stop_reason: string | null;
  token_usage: Record<string, number> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export function isActiveSubagentBatch(batch: SubagentBatch): boolean {
  return ["queued", "running", "paused"].includes(batch.status);
}

export function completedSubagentBatchItems(batch: SubagentBatch): number {
  return batch.counts.succeeded + batch.counts.failed + batch.counts.cancelled;
}

export function subagentBatchProgress(batch: SubagentBatch): number {
  if (!Number.isFinite(batch.total_items) || batch.total_items <= 0) return 0;
  const completed = completedSubagentBatchItems(batch);
  if (!Number.isFinite(completed)) return 0;
  return Math.min(100, Math.max(0, (completed / batch.total_items) * 100));
}
