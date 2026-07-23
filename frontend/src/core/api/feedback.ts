import { getBackendBaseURL } from "../config";

import { fetch } from "./fetcher";

export interface FeedbackData {
  feedback_id: string;
  rating: number;
  comment: string | null;
  tags?: string[];
}

/** Language-neutral thumbs-down reason slugs; must match the backend's
 *  VALID_FEEDBACK_TAGS (deerflow.domain.feedback.model). */
export const FEEDBACK_TAG_SLUGS = [
  "incorrect",
  "not_as_expected",
  "slow",
  "style_tone",
  "safety_legal",
  "other",
] as const;
export type FeedbackTagSlug = (typeof FEEDBACK_TAG_SLUGS)[number];

export async function upsertFeedback(
  threadId: string,
  runId: string,
  rating: number,
  comment?: string,
  tags?: string[],
): Promise<FeedbackData> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/feedback`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rating,
        comment: comment ?? null,
        tags: tags ?? [],
      }),
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
