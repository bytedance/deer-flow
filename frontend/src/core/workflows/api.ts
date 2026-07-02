import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type WorkflowEnvelope = {
  workflow_id: string;
  workflow_kind: string;
  source_type: string;
  source?: string | null;
  idempotency_key?: string | null;
  external_message_ref?: string | null;
  thread_id?: string | null;
  run_id?: string | null;
  checkpoint_ns?: string | null;
  checkpoint_id?: string | null;
  status: string;
  error?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export type WorkflowTimelineEvent = {
  kind: "workflow_event" | "run_event";
  seq?: number;
  event_type: string;
  category?: string;
  created_at?: string;
  thread_id?: string | null;
  run_id?: string | null;
  content?: unknown;
  metadata?: Record<string, unknown>;
};

export type WorkflowTimelineResponse = {
  workflow: WorkflowEnvelope;
  run?: Record<string, unknown> | null;
  timeline: WorkflowTimelineEvent[];
  workflow_events: Record<string, unknown>[];
  run_events: Record<string, unknown>[];
};

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String(payload.detail)
        : `Request failed with ${response.status}`;
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function fetchWorkflowByRun(
  runId: string,
): Promise<WorkflowEnvelope | null> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/workflows/by-run/${encodeURIComponent(runId)}`,
  );
  if (response.status === 404) {
    return null;
  }
  return readJson<WorkflowEnvelope>(response);
}

export async function fetchWorkflowTimeline(
  workflowId: string,
): Promise<WorkflowTimelineResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/workflows/${encodeURIComponent(
      workflowId,
    )}/timeline`,
  );
  return readJson<WorkflowTimelineResponse>(response);
}

export async function fetchWorkflowTraceByRun(
  runId: string,
): Promise<WorkflowTimelineResponse | null> {
  const workflow = await fetchWorkflowByRun(runId);
  if (!workflow) {
    return null;
  }
  return fetchWorkflowTimeline(workflow.workflow_id);
}
