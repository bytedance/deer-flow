import { getBackendBaseURL } from "../config";

import { requestWithWorkspace, type WorkspaceRequestOptions } from "./request";

export interface FeedbackData {
  feedback_id: string;
  rating: number;
  comment: string | null;
}

export async function upsertFeedback(
  threadId: string,
  runId: string,
  rating: number,
  comment?: string,
  options?: WorkspaceRequestOptions,
): Promise<FeedbackData> {
  return requestWithWorkspace(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/feedback`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, comment: comment ?? null }),
    },
    async (res) => {
      if (!res.ok) {
        throw new Error(`Failed to submit feedback: ${res.status}`);
      }
      return res.json() as Promise<FeedbackData>;
    },
    options,
  );
}

export async function deleteFeedback(
  threadId: string,
  runId: string,
  options?: WorkspaceRequestOptions,
): Promise<void> {
  return requestWithWorkspace(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/feedback`,
    { method: "DELETE" },
    async (res) => {
      if (!res.ok && res.status !== 404) {
        throw new Error(`Failed to delete feedback: ${res.status}`);
      }
    },
    options,
  );
}
