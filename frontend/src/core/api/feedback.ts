import { getBackendBaseURL } from "../config";

import { fetch } from "./fetcher";

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
): Promise<FeedbackData> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/feedback`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, comment: comment ?? null }),
    },
  );
  if (!res.ok) {
    throw new Error(`Failed to submit feedback: ${res.status}`);
  }
  return res.json();
}

export async function deleteFeedback(
  threadId: string,
  runId: string,
): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/feedback`,
    { method: "DELETE" },
  );
  if (!res.ok && res.status !== 404) {
    throw new Error(`Failed to delete feedback: ${res.status}`);
  }
}
