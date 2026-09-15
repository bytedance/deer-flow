import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { SubagentBatch, SubagentBatchItem } from "./types";

function batchUrl(threadId: string, path = ""): string {
  return `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/subagent-batches${path}`;
}

async function json<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) await throwGatewayApiError(response, fallback);
  return response.json() as Promise<T>;
}

export async function fetchSubagentBatches(
  threadId: string,
): Promise<SubagentBatch[]> {
  return json(
    await fetch(`${batchUrl(threadId)}?limit=20`),
    "Failed to load subagent batches",
  );
}

export async function fetchSubagentBatchItems(
  threadId: string,
  batchId: string,
  options: {
    offset?: number;
    limit?: number;
    status?: SubagentBatchItem["status"];
  } = {},
): Promise<SubagentBatchItem[]> {
  const params = new URLSearchParams({
    offset: String(options.offset ?? 0),
    limit: String(options.limit ?? 100),
  });
  if (options.status) params.set("status", options.status);
  return json(
    await fetch(
      batchUrl(threadId, `/${encodeURIComponent(batchId)}/items?${params}`),
    ),
    "Failed to load batch items",
  );
}

export async function controlSubagentBatch(
  threadId: string,
  batchId: string,
  action: "pause" | "resume" | "cancel",
): Promise<SubagentBatch> {
  return json(
    await fetch(
      batchUrl(threadId, `/${encodeURIComponent(batchId)}/${action}`),
      { method: "POST" },
    ),
    `Failed to ${action} subagent batch`,
  );
}

export async function retrySubagentBatchItem(
  threadId: string,
  batchId: string,
  itemId: string,
): Promise<SubagentBatchItem> {
  return json(
    await fetch(
      batchUrl(
        threadId,
        `/${encodeURIComponent(batchId)}/items/${encodeURIComponent(itemId)}/retry`,
      ),
      { method: "POST" },
    ),
    "Failed to retry subagent batch item",
  );
}

export function subagentBatchResultsUrl(
  threadId: string,
  batchId: string,
): string {
  return batchUrl(threadId, `/${encodeURIComponent(batchId)}/results.jsonl`);
}
