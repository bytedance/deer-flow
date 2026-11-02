import { z } from "zod";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type RunInputMode = "queue" | "steer";
export const runInputSchema = z.object({
  id: z.string(),
  target_run_id: z.string(),
  message_id: z.string(),
  text: z.string(),
  mode: z.enum(["queue", "steer"]),
  status: z.enum([
    "pending",
    "applying",
    "dispatching",
    "applied",
    "not_applied",
    "cancelled",
  ]),
  created_at: z.string(),
  run_id: z.string().optional(),
});
export type RunInput = z.infer<typeof runInputSchema>;
export const runInputsKey = (threadId: string) =>
  ["threads", threadId, "inputs"] as const;

async function readResponse(response: Response) {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new Error(
      typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`,
    );
  }
  return response.json() as Promise<unknown>;
}

export async function fetchRunInputState(
  threadId: string,
  signal?: AbortSignal,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/inputs`,
    { signal },
  );
  return z
    .object({
      items: z.array(runInputSchema),
      active_run_id: z.string().nullable(),
    })
    .parse(await readResponse(response));
}

export async function fetchRunInputs(threadId: string, signal?: AbortSignal) {
  return (await fetchRunInputState(threadId, signal)).items;
}

export async function submitRunInput({
  threadId,
  runId,
  requestId,
  text,
  mode,
  context,
  signal,
}: {
  threadId: string;
  runId: string;
  requestId: string;
  text: string;
  mode: RunInputMode;
  context?: Record<string, unknown>;
  signal?: AbortSignal;
}) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/inputs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: requestId,
        text,
        mode,
        context: context ?? {},
      }),
      signal,
    },
  );
  return runInputSchema.parse(await readResponse(response));
}

export async function changeRunInput(
  threadId: string,
  input: RunInput,
  action: "cancel" | "retry",
  signal?: AbortSignal,
) {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(input.target_run_id)}/inputs/${encodeURIComponent(input.id)}`;
  return readResponse(
    await fetch(action === "retry" ? `${url}/retry` : url, {
      method: action === "retry" ? "POST" : "DELETE",
      signal,
    }),
  );
}
