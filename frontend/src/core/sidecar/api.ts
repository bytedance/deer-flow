import { getAPIClient } from "@/core/api";
import {
  fetch as fetchWithAuth,
  type WorkspaceRESTClient,
} from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import type { AgentThread } from "@/core/threads";
import type { ThreadRequestOptions } from "@/core/threads/api";

import type { SidecarContext } from "./context";
import {
  SIDECAR_METADATA_KEY,
  buildSidecarThreadMetadata,
  isSidecarThread,
} from "./thread";

type SidecarThreadSearchQuery = {
  metadata: Record<string, unknown>;
  limit: number;
  offset: number;
  sortBy: "updated_at";
  sortOrder: "desc";
};

export type SidecarThreadSearchClient = {
  threads: {
    search: (query: SidecarThreadSearchQuery) => Promise<AgentThread[]>;
  };
};

// The find-then-create flow is two independent round-trips with no backend
// upsert, so a double-click on "Ask in side chat" or two callers racing on the
// same parent thread can each create a duplicate sidecar thread. Coalesce
// concurrent creates for the same parent behind a single in-flight promise so
// only one thread is created; the entry is cleared once it settles.
const inFlightCreates = new Map<string, Promise<AgentThread>>();
// A fixed client is unique to one actor/workspace/reset lifetime. An old
// pending create must never block or supply a result to another lifetime.
const workspaceCreates = new WeakMap<
  WorkspaceRESTClient,
  Map<string, Promise<AgentThread>>
>();

export async function createSidecarThread(
  {
    parentThreadId,
    context,
  }: { parentThreadId: string; context: SidecarContext | SidecarContext[] },
  options?: ThreadRequestOptions,
): Promise<AgentThread> {
  options?.signal?.throwIfAborted();
  let pendingCreates = inFlightCreates;
  if (options) {
    const existing = workspaceCreates.get(options.rest);
    pendingCreates = existing ?? new Map<string, Promise<AgentThread>>();
    if (!existing) workspaceCreates.set(options.rest, pendingCreates);
  }
  const inFlight = pendingCreates.get(parentThreadId);
  if (inFlight) {
    return inFlight;
  }

  const request = createSidecarThreadRequest(
    { parentThreadId, context },
    options,
  );
  pendingCreates.set(parentThreadId, request);
  try {
    return await request;
  } finally {
    if (pendingCreates.get(parentThreadId) === request) {
      pendingCreates.delete(parentThreadId);
    }
  }
}

async function createSidecarThreadRequest(
  {
    parentThreadId,
    context,
  }: { parentThreadId: string; context: SidecarContext | SidecarContext[] },
  options?: ThreadRequestOptions,
): Promise<AgentThread> {
  const response = await (options?.rest.fetch ?? fetchWithAuth)(
    `${getBackendBaseURL()}/api/threads`,
    {
      method: "POST",
      ...(options?.signal ? { signal: options.signal } : {}),
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        metadata: buildSidecarThreadMetadata(parentThreadId, context),
      }),
    },
  );

  const decode = async (response: Response) => {
    if (!response.ok) throw new Error("Failed to create side conversation.");
    return (await response.json()) as AgentThread;
  };
  return options ? options.rest.consume(response, decode) : decode(response);
}

export async function findLatestSidecarThread({
  parentThreadId,
  isMock,
  signal,
  apiClient = getAPIClient(isMock) as SidecarThreadSearchClient,
}: {
  parentThreadId: string;
  isMock?: boolean;
  apiClient?: SidecarThreadSearchClient;
  signal?: AbortSignal;
}): Promise<AgentThread | null> {
  signal?.throwIfAborted();
  const response = await apiClient.threads.search({
    metadata: {
      [SIDECAR_METADATA_KEY]: true,
      parent_thread_id: parentThreadId,
    },
    limit: 1,
    offset: 0,
    sortBy: "updated_at",
    sortOrder: "desc",
  });

  signal?.throwIfAborted();
  return (
    response.find(
      (thread) =>
        isSidecarThread(thread) &&
        thread.metadata?.parent_thread_id === parentThreadId,
    ) ?? null
  );
}
