import type { ThreadState } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";

import type { AgentThread, AgentThreadState } from "./types";

export const DEMO_THREAD_IDS = [
  "21cfea46-34bd-4aa6-9e1f-3009452fbeb9",
  "3823e443-4e2b-4679-b496-a9506eae462b",
  "4f3e55ee-f853-43db-bfb3-7d1a411f03cb",
  "5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a",
  "7cfa5f8f-a2f8-47ad-acbd-da7137baf990",
  "7f9dc56c-e49c-4671-a3d2-c492ff4dce0c",
  "90040b36-7eba-4b97-ba89-02c3ad47a8b9",
  "ad76c455-5bf9-4335-8517-fc03834ab828",
  "b83fbb2a-4e36-4d82-9de0-7b2a02c2092a",
  "c02bb4d5-4202-490e-ae8f-ff4864fc0d2e",
  "d3e5adaf-084c-4dd5-9d29-94f1d6bccd98",
  "f4125791-0128-402a-8ca9-50e0947557e4",
  "fe3f7974-1bcb-4a01-a950-79673baafefd",
] as const;

export type ThreadSearchParams = NonNullable<
  Parameters<ThreadsClient["search"]>[0]
>;

export async function loadStaticDemoThreads(
  params: ThreadSearchParams = {},
): Promise<AgentThread[]> {
  const threads = await Promise.all(
    DEMO_THREAD_IDS.map((threadId) => loadStaticDemoThread(threadId)),
  );

  const sortBy = params.sortBy ?? "updated_at";
  const sortOrder = params.sortOrder ?? "desc";
  const sortedThreads = [...threads].sort((a, b) => {
    const aTimestamp = (a as unknown as Record<string, unknown>)[sortBy];
    const bTimestamp = (b as unknown as Record<string, unknown>)[sortBy];
    const aParsed = typeof aTimestamp === "string" ? Date.parse(aTimestamp) : 0;
    const bParsed = typeof bTimestamp === "string" ? Date.parse(bTimestamp) : 0;
    const aValue = Number.isNaN(aParsed) ? 0 : aParsed;
    const bValue = Number.isNaN(bParsed) ? 0 : bParsed;
    return sortOrder === "asc" ? aValue - bValue : bValue - aValue;
  });

  const offset = Math.max(0, Math.floor(params.offset ?? 0));
  const limit =
    typeof params.limit === "number"
      ? Math.max(0, Math.floor(params.limit))
      : sortedThreads.length;
  return sortedThreads.slice(offset, offset + limit);
}

export async function loadStaticDemoThread(
  threadId: string,
): Promise<AgentThread> {
  const response = await globalThis.fetch(
    `/demo/threads/${encodeURIComponent(threadId)}/thread.json`,
  );
  if (!response.ok) {
    throw new Error(`Failed to load demo thread ${threadId}`);
  }
  const thread = (await response.json()) as AgentThread;
  return {
    ...thread,
    thread_id: threadId,
    updated_at: thread.updated_at ?? thread.created_at,
  };
}

export function staticDemoThreadState(
  thread: AgentThread,
): ThreadState<AgentThreadState> {
  return {
    values: thread.values,
    next: [],
    checkpoint: {
      thread_id: thread.thread_id,
      checkpoint_ns: "",
      checkpoint_id: null,
      checkpoint_map: null,
    },
    metadata: thread.metadata ?? null,
    created_at: thread.updated_at ?? thread.created_at ?? null,
    parent_checkpoint: null,
    tasks: [],
  };
}
