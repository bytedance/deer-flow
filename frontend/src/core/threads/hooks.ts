import type { AIMessage, Message, Run } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  type QueryClient,
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";

import { getAPIClient } from "../api";
import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";
import { useI18n } from "../i18n/hooks";
import { isHiddenFromUIMessage } from "../messages/utils";
import type { FileInMessage } from "../messages/utils";
import type { LocalSettings } from "../settings";
import { isSidecarThread, SIDECAR_METADATA_KEY } from "../sidecar/thread";
import { useUpdateSubtask } from "../tasks/context";
import { taskEventToSubtaskUpdate } from "../tasks/lifecycle";
import { messageToStep } from "../tasks/steps";
import type { UploadedFileInfo } from "../uploads";
import { promptInputFilePartToFile, uploadFiles } from "../uploads";

import { branchThreadFromTurn, fetchThreadTokenUsage } from "./api";
import {
  buildThreadsSearchQueryOptions,
  DEFAULT_THREAD_SEARCH_PARAMS,
  filterThreadSearchResults,
  type ThreadSearchParams,
} from "./thread-search-query";
import { threadTokenUsageQueryKey } from "./token-usage";
import type {
  AgentThread,
  AgentThreadState,
  RunMessage,
  ThreadTokenUsageResponse,
} from "./types";

export type ToolEndEvent = {
  name: string;
  data: unknown;
};

export type ThreadStreamOptions = {
  threadId?: string | null | undefined;
  displayThreadId?: string | null | undefined;
  context: LocalSettings["context"];
  isMock?: boolean;
  onSend?: (threadId: string) => void;
  onStart?: (threadId: string, runId: string) => void;
  onFinish?: (state: AgentThreadState) => void;
  onToolEnd?: (event: ToolEndEvent) => void;
};

type SendMessageOptions = {
  additionalKwargs?: Record<string, unknown>;
  additionalInputMessages?: Message[];
  /**
   * Invoked exactly once when the send passes the in-flight guard and is
   * genuinely dispatched. It never fires on the early-return path, so callers
   * can safely perform one-time cleanup (e.g. clearing quoted references)
   * without losing state when a concurrent send is dropped.
   */
  onSent?: () => void;
};

type ThreadDeleteClient = {
  threads: {
    delete: (threadId: string) => Promise<unknown>;
    search: (query: Record<string, unknown>) => Promise<AgentThread[]>;
  };
};

type ThreadSidecarSearchClient = {
  threads: {
    search: (query: Record<string, unknown>) => Promise<AgentThread[]>;
  };
};

type RegeneratePrepareResponse = {
  input: Partial<AgentThreadState>;
  checkpoint: {
    checkpoint_ns: string;
    checkpoint_id: string;
    checkpoint_map: Record<string, unknown> | null;
  };
  metadata: Record<string, unknown>;
  target_run_id: string;
};

export function buildThreadSubmitMessages({
  text,
  additionalKwargs,
  additionalInputMessages = [],
  filesForSubmit = [],
}: {
  text: string;
  additionalKwargs?: Record<string, unknown>;
  additionalInputMessages?: Message[];
  filesForSubmit?: FileInMessage[];
}): Message[] {
  return [
    ...additionalInputMessages,
    {
      type: "human",
      content: [
        {
          type: "text",
          text,
        },
      ],
      additional_kwargs: {
        ...additionalKwargs,
        ...(filesForSubmit.length > 0 ? { files: filesForSubmit } : {}),
      },
    } as Message,
  ];
}

const EMPTY_THREAD_VALUES: AgentThreadState = {
  title: "",
  messages: [],
  artifacts: [],
  todos: [],
};

function isNonEmptyString(value: string | undefined): value is string {
  return typeof value === "string" && value.length > 0;
}

const SUMMARIZATION_MIDDLEWARE_UPDATE_KEYS = new Set([
  "SummarizationMiddleware.before_model",
  "DeerFlowSummarizationMiddleware.before_model",
]);

function messageIdentity(message: Message): string | undefined {
  if (
    "tool_call_id" in message &&
    typeof message.tool_call_id === "string" &&
    message.tool_call_id.length > 0
  ) {
    return `tool:${message.tool_call_id}`;
  }
  if (typeof message.id === "string" && message.id.length > 0) {
    return `message:${message.id}`;
  }
  return undefined;
}

function dedupeMessagesByIdentity(messages: Message[]): Message[] {
  const lastIndexByIdentity = new Map<string, number>();
  const lastVisibleIndexByIdentity = new Map<string, number>();

  // This is a UI-display dedupe rule, not a general LangChain message-stream
  // contract. Hidden messages that share an identity with a visible message are
  // treated as control messages for this merged view; hidden messages carrying
  // independent tracing/task semantics should use a distinct id or a custom
  // stream/state channel instead of relying on message dedupe preservation.
  const preservedTurnDurations = new Map<string, number>();
  messages.forEach((message, index) => {
    const identity = messageIdentity(message);
    if (identity) {
      lastIndexByIdentity.set(identity, index);
      if (!isHiddenFromUIMessage(message)) {
        lastVisibleIndexByIdentity.set(identity, index);
      }
      if (message.additional_kwargs?.turn_duration !== undefined) {
        preservedTurnDurations.set(
          identity,
          message.additional_kwargs.turn_duration as number,
        );
      }
    }
  });

  return messages
    .filter((message, index) => {
      const identity = messageIdentity(message);
      if (!identity) {
        return true;
      }
      const visibleIndex = lastVisibleIndexByIdentity.get(identity);
      if (visibleIndex !== undefined) {
        return visibleIndex === index;
      }
      return lastIndexByIdentity.get(identity) === index;
    })
    .map((message) => {
      const identity = messageIdentity(message);
      if (
        identity &&
        preservedTurnDurations.has(identity) &&
        message.additional_kwargs?.turn_duration === undefined
      ) {
        return {
          ...message,
          additional_kwargs: {
            ...message.additional_kwargs,
            turn_duration: preservedTurnDurations.get(identity),
          },
        } as Message;
      }
      return message;
    });
}

function dedupeRunMessagesByIdentity(messages: RunMessage[]): RunMessage[] {
  const lastIndexByIdentity = new Map<string, number>();
  messages.forEach((message, index) => {
    const identity = messageIdentity(message.content);
    if (identity) {
      lastIndexByIdentity.set(`${message.run_id}:${identity}`, index);
    }
  });

  return messages.filter((message, index) => {
    const identity = messageIdentity(message.content);
    if (!identity) {
      return true;
    }
    return lastIndexByIdentity.get(`${message.run_id}:${identity}`) === index;
  });
}

export function removeSetItems<T>(
  values: ReadonlySet<T>,
  itemsToRemove: Iterable<T>,
) {
  const next = new Set(values);
  for (const item of itemsToRemove) {
    next.delete(item);
  }
  return next;
}

export function buildVisibleHistoryMessages(
  messageRows: RunMessage[],
  supersededRunIds: ReadonlySet<string>,
) {
  const visibleRows = messageRows.filter(
    (message) => !supersededRunIds.has(message.run_id),
  );
  return dedupeMessagesByIdentity([
    // Carry the owning run_id onto the content message so historical subtask
    // cards can fetch their persisted step history on expand (#3779). run_id
    // lives on the RunMessage wrapper and would otherwise be dropped here.
    ...visibleRows.map((message) => ({
      ...message.content,
      run_id: message.run_id,
    })),
  ]);
}

export type ThreadMessagesPageResponse = {
  data: RunMessage[];
  has_more: boolean;
  next_before_seq: number | null;
};

export function getThreadHistoryNextPageParam(
  lastPage: ThreadMessagesPageResponse,
): number | undefined {
  if (!lastPage.has_more) {
    return undefined;
  }
  if (lastPage.next_before_seq === null) {
    console.warn(
      "Thread history returned has_more without next_before_seq; pagination cannot continue.",
    );
    return undefined;
  }
  return lastPage.next_before_seq;
}

export const threadHistoryQueryKey = (threadId: string) =>
  ["thread-messages", threadId] as const;

export function buildThreadMessagesPageUrl(
  baseUrl: string,
  threadId: string,
  beforeSeq?: number,
) {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "");
  const path = `/api/threads/${encodeURIComponent(threadId)}/messages/page`;
  const url = new URL(
    `${normalizedBaseUrl}${path}`,
    typeof window !== "undefined" ? window.location.origin : "http://localhost",
  );
  if (beforeSeq !== undefined) {
    url.searchParams.set("before_seq", String(beforeSeq));
  }
  return normalizedBaseUrl ? url.toString() : `${url.pathname}${url.search}`;
}

export function flattenThreadHistoryPages(
  pages: ThreadMessagesPageResponse[],
): RunMessage[] {
  return dedupeRunMessagesByIdentity(
    pages
      .slice()
      .reverse()
      .flatMap((page) => page.data),
  );
}

export function mergeMessages(
  historyMessages: Message[],
  threadMessages: Message[],
  optimisticMessages: Message[],
): Message[] {
  const savedTurnDurations = new Map<string, number>();
  for (const msg of historyMessages) {
    const identity = messageIdentity(msg);
    if (identity && msg.additional_kwargs?.turn_duration !== undefined) {
      savedTurnDurations.set(
        identity,
        msg.additional_kwargs.turn_duration as number,
      );
    }
  }

  const canonical = dedupeMessagesByIdentity(historyMessages);
  const live = dedupeMessagesByIdentity(threadMessages);
  const canonicalByIdentity = new Map(
    canonical.flatMap((message) => {
      const identity = messageIdentity(message);
      return identity ? [[identity, message] as const] : [];
    }),
  );
  const replacementByIdentity = new Map<string, Message>();
  // This uses the same identity-anchor weaving shape as
  // resolveTransientHistoryBridge, but intentionally remains separate: live
  // messages may replace canonical copies and identity-less entries survive.
  const beforeAnchor = new Map<string, Message[]>();
  let pending: Message[] = [];
  let lastAnchorIdentity: string | undefined;
  let hasSharedAnchor = false;

  // A summarized checkpoint is not necessarily a contiguous history suffix:
  // middleware may retain protected prompt/input messages at the front and a
  // recent tail at the back. Treat every shared identity as an ordering anchor,
  // replacing the canonical copy in place. New live messages are woven before
  // the next shared anchor (or after the last one), so a protected early input
  // can never be moved to the tail by global last-copy deduplication.
  for (const message of live) {
    const identity = messageIdentity(message);
    const canonicalMessage = identity
      ? canonicalByIdentity.get(identity)
      : undefined;
    if (!identity || !canonicalMessage) {
      pending.push(message);
      continue;
    }

    if (pending.length > 0 && hasSharedAnchor) {
      beforeAnchor.set(identity, [
        ...(beforeAnchor.get(identity) ?? []),
        ...pending,
      ]);
    }
    // A summarized checkpoint may start with a protected message whose true
    // canonical position is separated from this anchor by unloaded pages.
    // Suppress that ambiguous prefix instead of visually collapsing the gap.
    pending = [];
    hasSharedAnchor = true;
    lastAnchorIdentity = identity;

    // A hidden checkpoint control message must not replace a visible canonical
    // user turn that happens to reuse its identity. In every other case the
    // live checkpoint copy is fresher and replaces history without moving it.
    if (
      !isHiddenFromUIMessage(message) ||
      isHiddenFromUIMessage(canonicalMessage)
    ) {
      replacementByIdentity.set(identity, message);
    }
  }

  let canonicalAndLive: Message[];
  if (!lastAnchorIdentity) {
    canonicalAndLive = [...canonical, ...live];
  } else {
    canonicalAndLive = [];
    for (const message of canonical) {
      const identity = messageIdentity(message);
      if (identity) {
        canonicalAndLive.push(...(beforeAnchor.get(identity) ?? []));
      }
      const replacement = identity
        ? replacementByIdentity.get(identity)
        : undefined;
      canonicalAndLive.push(replacement ?? message);
    }
    // A trailing live-only segment is known to come after the last shared
    // anchor, but that anchor may not be the end of canonical history (for
    // example, another client may have persisted newer rows). Preserve the
    // canonical source order before appending the live tail.
    canonicalAndLive.push(...pending);
  }

  const merged = dedupeMessagesByIdentity([
    ...canonicalAndLive,
    ...optimisticMessages,
  ]);

  return merged.map((message) => {
    const identity = messageIdentity(message);
    if (
      identity &&
      savedTurnDurations.has(identity) &&
      message.additional_kwargs?.turn_duration === undefined
    ) {
      return {
        ...message,
        additional_kwargs: {
          ...message.additional_kwargs,
          turn_duration: savedTurnDurations.get(identity),
        },
      } as Message;
    }
    return message;
  });
}

/**
 * Derive the live turns that context summarization is about to drop and that
 * therefore need a short-lived visual bridge until run-event history catches up.
 *
 * Summarization emits `RemoveMessage(ALL)` + a hidden summary + the retained
 * tail. Everything in the current live thread before the first retained visible
 * message is being removed; we keep those (minus the summary control messages
 * already tracked) so the UI can still show the full conversation (#3825).
 */
export function computeSummarizationTransientMessages(
  currentMessages: Message[],
  summarizationMessages: Message[],
  summarizedMessageIds: ReadonlySet<string>,
): Message[] {
  const firstRetainedVisibleIdentity = summarizationMessages
    .filter((message) => message.type !== "remove")
    .filter((message) => !isHiddenFromUIMessage(message))
    .map(messageIdentity)
    .find(isNonEmptyString);

  const moved: Message[] = [];
  for (const message of currentMessages) {
    if (
      firstRetainedVisibleIdentity &&
      messageIdentity(message) === firstRetainedVisibleIdentity
    ) {
      break;
    }
    if (!summarizedMessageIds.has(message.id ?? "")) {
      moved.push(message);
    }
  }
  return moved;
}

/**
 * Overlay messages rescued from context summarization on top of the
 * (possibly stale) visible history so the merged view never drops them.
 *
 * Background (#3825): after summarization the backend removes every live
 * message (`RemoveMessage(ALL)`) while canonical run events can still be
 * waiting for the journal flush/refetch lifecycle. Reading the captured turns
 * from a synchronous transient buffer keeps the merge correct during that gap.
 *
 * Canonical history is cursor-paginated from newest to oldest. A rescued turn
 * can therefore be older than the first row in the currently loaded page even
 * though both came from the same pre-compression checkpoint. ``bridgeOrder``
 * retains identities that canonical history has already confirmed so missing
 * rescued turns can be inserted next to an overlapping anchor instead of being
 * blindly appended after the newest page. Canonical copies always win.
 */
export function resolveTransientHistoryBridge(
  visibleHistory: Message[],
  transientMessages: Message[],
  bridgeOrder: readonly string[] = transientMessages
    .map(messageIdentity)
    .filter(isNonEmptyString),
): Message[] {
  if (transientMessages.length === 0) {
    return visibleHistory;
  }
  const presentIdentities = new Set(
    visibleHistory.map(messageIdentity).filter(isNonEmptyString),
  );
  const missing = transientMessages.filter((message) => {
    const identity = messageIdentity(message);
    // Identity-less messages are intentionally skipped: without a stable
    // identity they cannot be matched against history to drain or dedupe, so
    // overlaying them would risk a permanent duplicate. Canonical history will
    // surface them after the run journal is flushed and the page refetches.
    return identity !== undefined && !presentIdentities.has(identity);
  });
  if (missing.length === 0) {
    return visibleHistory;
  }

  const missingByIdentity = new Map(
    missing.flatMap((message) => {
      const identity = messageIdentity(message);
      return identity ? [[identity, message] as const] : [];
    }),
  );
  // This mirrors mergeMessages' identity-anchor weaving shape, but transient
  // messages never replace canonical copies and identity-less entries are
  // intentionally excluded to avoid permanent duplicates.
  const beforeAnchor = new Map<string, Message[]>();
  const emittedMissingIdentities = new Set<string>();
  let pending: Message[] = [];
  let lastAnchorIdentity: string | undefined;
  let hasCanonicalAnchor = false;

  for (const identity of bridgeOrder) {
    if (presentIdentities.has(identity)) {
      if (pending.length > 0 && hasCanonicalAnchor) {
        beforeAnchor.set(identity, [
          ...(beforeAnchor.get(identity) ?? []),
          ...pending,
        ]);
      }
      // The prefix before the first loaded anchor has no trustworthy position:
      // cursor pages containing its intervening history may not be loaded yet.
      pending = [];
      hasCanonicalAnchor = true;
      lastAnchorIdentity = identity;
      continue;
    }
    const message = missingByIdentity.get(identity);
    if (message && !emittedMissingIdentities.has(identity)) {
      pending.push(message);
      emittedMissingIdentities.add(identity);
    }
  }

  // No bridge identity overlaps canonical history. This is the original
  // persistence-gap case: loaded history is older and the rescued live turns
  // belong after it.
  if (!lastAnchorIdentity) {
    return [...visibleHistory, ...missing];
  }

  // A candidate added before its ordering snapshot (or carrying an identity
  // absent from that snapshot) cannot be anchored. Keep it in capture order at
  // the trailing edge of the anchored bridge rather than dropping it.
  for (const message of missing) {
    const identity = messageIdentity(message);
    if (identity && !emittedMissingIdentities.has(identity)) {
      pending.push(message);
      emittedMissingIdentities.add(identity);
    }
  }

  const resolved: Message[] = [];
  for (const message of visibleHistory) {
    const identity = messageIdentity(message);
    if (identity) {
      resolved.push(...(beforeAnchor.get(identity) ?? []));
    }
    resolved.push(message);
    if (identity === lastAnchorIdentity) {
      resolved.push(...pending);
    }
  }
  return resolved;
}

export function mergeTransientHistoryBridge(
  currentBridge: Message[],
  capturedMessages: Message[],
): Message[] {
  const merged = dedupeMessagesByIdentity(currentBridge);
  const indexByIdentity = new Map<string, number>();
  merged.forEach((message, index) => {
    const identity = messageIdentity(message);
    if (identity) {
      indexByIdentity.set(identity, index);
    }
  });

  for (const captured of dedupeMessagesByIdentity(capturedMessages)) {
    const identity = messageIdentity(captured);
    const existingIndex = identity ? indexByIdentity.get(identity) : undefined;
    if (existingIndex === undefined) {
      if (identity) {
        indexByIdentity.set(identity, merged.length);
      }
      merged.push(captured);
      continue;
    }

    const existing = merged[existingIndex];
    if (
      existing &&
      (!isHiddenFromUIMessage(captured) || isHiddenFromUIMessage(existing))
    ) {
      // Refresh the buffered snapshot without moving its first-known
      // chronological position. Repeated compression can recapture protected
      // prefix messages before a newer tail.
      merged[existingIndex] = captured;
    }
  }
  return merged;
}

/**
 * Preserve the complete checkpoint-relative identity order independently from
 * bridge candidates. Confirmed candidates are pruned from the render buffer,
 * but their identities remain useful as non-rendering pagination anchors.
 */
export function mergeTransientHistoryBridgeOrder(
  currentOrder: readonly string[],
  capturedMessages: Message[],
): string[] {
  const capturedOrder = dedupeMessagesByIdentity(capturedMessages)
    .map(messageIdentity)
    .filter(isNonEmptyString);
  const merged = [...currentOrder];
  const seen = new Set(currentOrder);
  for (const identity of capturedOrder) {
    if (!seen.has(identity)) {
      seen.add(identity);
      merged.push(identity);
    }
  }
  return merged;
}

export function resolveThreadTransientHistoryBridge(
  visibleHistory: Message[],
  transientMessages: Message[],
  bridgeThreadId: string | null,
  currentThreadId: string | null | undefined,
  bridgeOrder?: readonly string[],
): Message[] {
  if (!bridgeThreadId || bridgeThreadId !== currentThreadId) {
    return visibleHistory;
  }
  return resolveTransientHistoryBridge(
    visibleHistory,
    transientMessages,
    bridgeOrder,
  );
}

/**
 * Drop transient-buffer entries that canonical history has already
 * absorbed. This keeps the buffer a transient bridge across the async gap
 * rather than a second long-lived source of truth — otherwise a stale copy
 * could resurrect a message that history later filtered out (e.g. a superseded
 * or regenerated run).
 */
export function pruneConfirmedTransientMessages(
  transientMessages: Message[],
  visibleHistory: Message[],
): Message[] {
  if (transientMessages.length === 0) {
    return transientMessages;
  }
  const confirmedIdentities = new Set(
    visibleHistory.map(messageIdentity).filter(isNonEmptyString),
  );
  return transientMessages.filter((message) => {
    const identity = messageIdentity(message);
    return !identity || !confirmedIdentities.has(identity);
  });
}

function getMessagesAfterBaseline(
  messages: Message[],
  baselineMessageIds: ReadonlySet<string>,
): Message[] {
  return messages.filter((message) => {
    const id = messageIdentity(message);
    return !id || !baselineMessageIds.has(id);
  });
}

export function getVisibleOptimisticMessages(
  optimisticMessages: Message[],
  previousHumanMessageCount: number,
  currentHumanMessageCount: number,
): Message[] {
  if (
    optimisticMessages.some((message) => message.type === "human") &&
    currentHumanMessageCount > previousHumanMessageCount
  ) {
    return [];
  }
  return optimisticMessages;
}

export function getSummarizationMiddlewareMessages(
  data: unknown,
): Message[] | undefined {
  if (typeof data !== "object" || data === null) {
    return undefined;
  }

  for (const [key, update] of Object.entries(data)) {
    if (!SUMMARIZATION_MIDDLEWARE_UPDATE_KEYS.has(key)) {
      continue;
    }
    if (typeof update !== "object" || update === null) {
      continue;
    }

    const messages = Reflect.get(update, "messages");
    if (Array.isArray(messages)) {
      return [...messages] as Message[];
    }
  }

  return undefined;
}

export function upsertThreadInSearchCache(
  queryClient: QueryClient,
  thread: AgentThread,
) {
  queryClient.setQueriesData(
    {
      queryKey: ["threads", "search"],
      exact: false,
    },
    (oldData: Array<AgentThread> | undefined) => {
      if (!oldData) {
        return [thread];
      }

      const existingIndex = oldData.findIndex(
        (t) => t.thread_id === thread.thread_id,
      );
      if (existingIndex === -1) {
        return [thread, ...oldData];
      }

      return oldData.map((t, index) => {
        if (index !== existingIndex) {
          return t;
        }
        return {
          ...thread,
          ...t,
          metadata: {
            ...(thread.metadata ?? {}),
            ...(t.metadata ?? {}),
          },
          values: {
            ...thread.values,
            ...t.values,
          },
        };
      });
    },
  );
}

export function upsertThreadInInfiniteCache(
  queryClient: QueryClient,
  thread: AgentThread,
) {
  queryClient.setQueriesData(
    {
      queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      exact: false,
    },
    (oldData: InfiniteData<AgentThread[]> | undefined) => {
      if (!oldData) {
        return oldData;
      }

      const merged = oldData.pages.map((page) =>
        page.map((t) =>
          t.thread_id === thread.thread_id
            ? {
                ...thread,
                ...t,
                metadata: {
                  ...(thread.metadata ?? {}),
                  ...(t.metadata ?? {}),
                },
                values: {
                  ...thread.values,
                  ...t.values,
                },
              }
            : t,
        ),
      );

      const exists = merged.some((page) =>
        page.some((t) => t.thread_id === thread.thread_id),
      );
      if (exists) {
        return { ...oldData, pages: merged };
      }

      const firstPage = merged[0] ?? [];
      const restPages = merged.slice(1);
      return {
        ...oldData,
        pages: [[thread, ...firstPage], ...restPages],
      };
    },
  );
}

export function invalidateStoppedThreadCaches(
  queryClient: QueryClient,
  threadId: string | null | undefined,
  isMock = false,
) {
  void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
  void queryClient.invalidateQueries({
    queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
  });

  if (!threadId || isMock) {
    return;
  }

  void queryClient.invalidateQueries({ queryKey: ["thread", threadId] });
  void queryClient.invalidateQueries({
    queryKey: threadHistoryQueryKey(threadId),
  });
  void queryClient.invalidateQueries({
    queryKey: ["thread", "metadata", threadId, isMock],
  });
  void queryClient.invalidateQueries({
    queryKey: threadTokenUsageQueryKey(threadId),
  });
}

export const STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS = 1500;

function scheduleStoppedThreadFinalizationRefetch(
  queryClient: QueryClient,
  threadId: string | null | undefined,
  isMock = false,
) {
  if (isMock) {
    return;
  }
  globalThis.setTimeout(() => {
    invalidateStoppedThreadCaches(queryClient, threadId, isMock);
  }, STOP_THREAD_FINALIZATION_REFETCH_DELAY_MS);
}

export async function stopThreadAndInvalidateCaches(
  queryClient: QueryClient,
  stop: () => Promise<void> | void,
  threadId: string | null | undefined,
  isMock = false,
) {
  try {
    await stop();
  } finally {
    invalidateStoppedThreadCaches(queryClient, threadId, isMock);
    scheduleStoppedThreadFinalizationRefetch(queryClient, threadId, isMock);
  }
}

function getStreamErrorMessage(error: unknown): string {
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  if (typeof error === "object" && error !== null) {
    const message = Reflect.get(error, "message");
    if (typeof message === "string" && message.trim()) {
      return message;
    }
    const nestedError = Reflect.get(error, "error");
    if (nestedError instanceof Error && nestedError.message.trim()) {
      return nestedError.message;
    }
    if (typeof nestedError === "string" && nestedError.trim()) {
      return nestedError;
    }
  }
  return "Request failed.";
}

async function readResponseErrorMessage(
  response: Response,
  fallback = "Request failed.",
) {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string" && data.detail.trim()) {
      return data.detail;
    }
  } catch {
    // Use the fallback below when the response body is not JSON.
  }
  return response.statusText || fallback;
}

function getHttpStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) {
    return undefined;
  }

  const status = Reflect.get(error, "status");
  if (typeof status === "number") {
    return status;
  }

  const response = Reflect.get(error, "response");
  if (typeof response === "object" && response !== null) {
    const responseStatus = Reflect.get(response, "status");
    if (typeof responseStatus === "number") {
      return responseStatus;
    }
  }

  return undefined;
}

function isThreadMissingError(error: unknown): boolean {
  const status = getHttpStatus(error);
  // Treat 403 like 404 here to avoid disclosing whether an inaccessible thread
  // exists; callers redirect stale/inaccessible URLs back to a blank chat.
  return status === 403 || status === 404;
}

export function useThreadStream({
  threadId,
  displayThreadId,
  context,
  isMock,
  onSend,
  onStart,
  onFinish,
  onToolEnd,
}: ThreadStreamOptions) {
  const { t } = useI18n();
  const currentViewThreadId = displayThreadId ?? threadId ?? null;
  const currentViewThreadIdRef = useRef(currentViewThreadId);
  currentViewThreadIdRef.current = currentViewThreadId;
  // Optimistic messages shown before the server stream responds.
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [optimisticThreadId, setOptimisticThreadId] = useState<string | null>(
    null,
  );
  const [liveMessagesThreadId, setLiveMessagesThreadId] = useState<
    string | null
  >(null);
  const [pendingSupersededRunIds, setPendingSupersededRunIds] = useState<
    ReadonlySet<string>
  >(() => new Set());
  const [pendingSupersededMessageIds, setPendingSupersededMessageIds] =
    useState<ReadonlySet<string>>(() => new Set());
  const [isUploading, setIsUploading] = useState(false);
  // Track the thread ID that is currently streaming to handle thread changes during streaming
  const [onStreamThreadId, setOnStreamThreadId] = useState(() => threadId);
  // Ref to track current thread ID across async callbacks without causing re-renders,
  // and to allow access to the current thread id in onUpdateEvent
  const threadIdRef = useRef<string | null>(threadId ?? null);
  const startedRef = useRef(false);
  const pendingUsageBaselineMessageIdsRef = useRef<Set<string>>(new Set());
  const listeners = useRef({
    onSend,
    onStart,
    onFinish,
    onToolEnd,
  });

  const {
    messages: history,
    hasMore: hasMoreHistory,
    loadMore: loadMoreHistory,
    loading: isHistoryLoading,
  } = useThreadHistory(onStreamThreadId ?? "", {
    enabled: !isMock,
    pendingSupersededRunIds,
  });

  // Keep listeners ref updated with latest callbacks
  useEffect(() => {
    listeners.current = { onSend, onStart, onFinish, onToolEnd };
  }, [onSend, onStart, onFinish, onToolEnd]);

  useEffect(() => {
    const normalizedThreadId = threadId ?? null;
    if (!normalizedThreadId) {
      // Reset when the UI moves back to a brand new unsaved thread.
      startedRef.current = false;
      setOnStreamThreadId(normalizedThreadId);
    } else {
      setOnStreamThreadId(normalizedThreadId);
    }
    threadIdRef.current = normalizedThreadId;
  }, [threadId]);

  const handleStreamStart = useCallback((_threadId: string, _runId: string) => {
    threadIdRef.current = _threadId;
    setOptimisticThreadId((currentOptimisticThreadId) => {
      const currentView = currentViewThreadIdRef.current;
      if (
        currentOptimisticThreadId &&
        (currentOptimisticThreadId === currentView ||
          currentOptimisticThreadId === _threadId)
      ) {
        return _threadId;
      }
      return currentOptimisticThreadId;
    });
    setLiveMessagesThreadId((currentLiveMessagesThreadId) => {
      const currentView = currentViewThreadIdRef.current;
      if (
        currentLiveMessagesThreadId &&
        (currentLiveMessagesThreadId === currentView ||
          currentLiveMessagesThreadId === _threadId)
      ) {
        return _threadId;
      }
      return currentLiveMessagesThreadId;
    });
    if (!startedRef.current) {
      listeners.current.onStart?.(_threadId, _runId);
      startedRef.current = true;
    }
    setOnStreamThreadId(_threadId);
  }, []);

  const queryClient = useQueryClient();
  const updateSubtask = useUpdateSubtask();

  const thread = useStream<AgentThreadState>({
    client: getAPIClient(isMock),
    assistantId: "lead_agent",
    threadId: onStreamThreadId,
    reconnectOnMount: true,
    fetchStateHistory: { limit: 1 },
    onCreated(meta) {
      handleStreamStart(meta.thread_id, meta.run_id);
      const now = new Date().toISOString();
      upsertThreadInSearchCache(queryClient, {
        thread_id: meta.thread_id,
        created_at: now,
        updated_at: now,
        metadata: context.agent_name ? { agent_name: context.agent_name } : {},
        status: "busy",
        values: {
          title: t.pages.newChat,
          messages: [],
          artifacts: [],
        },
        interrupts: {},
      });
      upsertThreadInInfiniteCache(queryClient, {
        thread_id: meta.thread_id,
        created_at: now,
        updated_at: now,
        metadata: context.agent_name ? { agent_name: context.agent_name } : {},
        status: "busy",
        values: {
          title: t.pages.newChat,
          messages: [],
          artifacts: [],
        },
        interrupts: {},
      });
      if (context.agent_name && !isMock) {
        void getAPIClient()
          .threads.update(meta.thread_id, {
            metadata: { agent_name: context.agent_name },
          })
          .catch(() => ({}));
      }
    },
    onLangChainEvent(event) {
      if (event.event === "on_tool_end") {
        listeners.current.onToolEnd?.({
          name: event.name,
          data: event.data,
        });
      }
    },
    onUpdateEvent(data) {
      const _messages = getSummarizationMiddlewareMessages(data);
      if (_messages && _messages.length >= 2) {
        for (const m of _messages) {
          // Backward-compat shim: pre-PR2 threads may still carry a synthetic
          // HumanMessage(name="summary") from the old summarization path. New
          // threads keep the summary in ThreadState.summary_text instead.
          if (m.name === "summary" && m.type === "human") {
            summarizedRef.current?.add(m.id ?? "");
          }
        }
        const transientMessages = computeSummarizationTransientMessages(
          messagesRef.current,
          _messages,
          summarizedRef.current ?? new Set<string>(),
        );
        transientHistoryOrderRef.current = mergeTransientHistoryBridgeOrder(
          transientHistoryOrderRef.current,
          transientMessages,
        );
        transientHistoryBridgeRef.current = mergeTransientHistoryBridge(
          transientHistoryBridgeRef.current,
          transientMessages,
        );
        transientHistoryThreadIdRef.current = threadIdRef.current;
        messagesRef.current = [];
      }

      const updates: Array<Partial<AgentThreadState> | null> = Object.values(
        data || {},
      );
      for (const update of updates) {
        if (update && "title" in update && update.title) {
          void queryClient.setQueriesData(
            {
              queryKey: ["threads", "search"],
              exact: false,
            },
            (oldData: Array<AgentThread> | undefined) => {
              return oldData?.map((t) => {
                if (t.thread_id === threadIdRef.current) {
                  return {
                    ...t,
                    values: {
                      ...t.values,
                      title: update.title,
                    },
                  };
                }
                return t;
              });
            },
          );
          const nextTitle: string = update.title;
          void queryClient.setQueriesData(
            {
              queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
              exact: false,
            },
            (oldData: InfiniteData<AgentThread[]> | undefined) =>
              mapInfiniteThreadsCache(
                oldData,
                (t): AgentThread =>
                  t.thread_id === threadIdRef.current
                    ? {
                        ...t,
                        values: {
                          ...t.values,
                          title: nextTitle,
                        },
                      }
                    : t,
              ),
          );
        }
      }
    },
    onCustomEvent(event: unknown) {
      // Narrow `event.type` once; taskEventToSubtaskUpdate already validated the
      // task_* events, so the per-branch re-narrowing below reads this single
      // source of truth instead of re-checking the object shape each time.
      const eventType =
        typeof event === "object" && event !== null && "type" in event
          ? (event as { type: unknown }).type
          : undefined;

      const taskUpdate = taskEventToSubtaskUpdate(event);
      if (taskUpdate) {
        updateSubtask(taskUpdate);
      }

      if (eventType === "task_running") {
        const e = event as {
          type: "task_running";
          task_id: string;
          message: AIMessage;
          message_index?: number;
        };
        // Accumulate the full step history instead of overwriting (#3779): keep
        // latestMessage for the collapsed-header tool-call hint, and append the
        // normalized step (assistant turn or tool output) to the timeline.
        updateSubtask({
          id: e.task_id,
          latestMessage: e.message,
          steps: [messageToStep(e.message, e.message_index ?? 0)],
        });
        return;
      }

      if (eventType === "llm_retry") {
        const e = event as { type: "llm_retry"; message?: unknown };
        if (typeof e.message === "string" && e.message.trim()) {
          toast(e.message);
        }
      }
    },
    onError(error) {
      setOptimisticMessages([]);
      setOptimisticThreadId(null);
      setLiveMessagesThreadId(null);
      setPendingSupersededRunIds(new Set());
      setPendingSupersededMessageIds(new Set());
      toast.error(getStreamErrorMessage(error));
      pendingUsageBaselineMessageIdsRef.current = new Set(
        messagesRef.current
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
      if (threadIdRef.current && !isMock) {
        void queryClient.invalidateQueries({
          queryKey: threadHistoryQueryKey(threadIdRef.current),
        });
        void queryClient.invalidateQueries({
          queryKey: threadTokenUsageQueryKey(threadIdRef.current),
        });
      }
    },
    onFinish(state) {
      listeners.current.onFinish?.(state.values);
      pendingUsageBaselineMessageIdsRef.current = new Set(
        messagesRef.current
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
      invalidateStoppedThreadCaches(queryClient, threadIdRef.current, isMock);
    },
  });

  const stopThread = useCallback(async () => {
    const stoppedThreadId =
      threadIdRef.current ?? displayThreadId ?? threadId ?? null;
    await stopThreadAndInvalidateCaches(
      queryClient,
      () => thread.stop(),
      stoppedThreadId,
      isMock,
    );
  }, [displayThreadId, isMock, queryClient, thread, threadId]);

  const hasVisibleStreamState =
    Boolean(threadId) || liveMessagesThreadId === currentViewThreadId;
  const persistedMessages = useMemo(
    () =>
      hasVisibleStreamState
        ? thread.messages.filter(
            (message) =>
              !message.id || !pendingSupersededMessageIds.has(message.id),
          )
        : [],
    [hasVisibleStreamState, pendingSupersededMessageIds, thread.messages],
  );
  const visibleHistory = useMemo(
    () => (threadId ? history : []),
    [history, threadId],
  );
  const humanMessageCount = persistedMessages.filter(
    (m) => m.type === "human",
  ).length;
  const latestMessageCountsRef = useRef({ humanMessageCount });
  const sendInFlightRef = useRef(false);
  const messagesRef = useRef<Message[]>([]);
  // Current-stream lifecycle bridge for messages removed from the checkpoint
  // tail before the canonical run-event page refetch observes the journal
  // flush. It is never appended into useThreadHistory's persisted pages.
  const transientHistoryBridgeRef = useRef<Message[]>([]);
  // Full identity order of each captured checkpoint. Confirmed bridge entries
  // are pruned from the message buffer, but remain here as non-rendering
  // anchors so an older rescue can be placed before a newest-first page.
  const transientHistoryOrderRef = useRef<string[]>([]);
  const transientHistoryThreadIdRef = useRef<string | null>(null);
  const summarizedRef = useRef<Set<string>>(null);
  // Track human message count before sending to prevent clearing optimistic
  // messages before the server's human message arrives (e.g. when AI messages
  // from "messages-tuple" events arrive before the input human message from
  // "values" events).
  const prevHumanMsgCountRef = useRef(humanMessageCount);

  latestMessageCountsRef.current = { humanMessageCount };
  summarizedRef.current ??= new Set<string>();

  // Reset thread-local pending UI state when switching between threads so
  // optimistic messages and in-flight guards do not leak across chat views.
  useEffect(() => {
    startedRef.current = false;
    sendInFlightRef.current = false;
    messagesRef.current = [];
    transientHistoryBridgeRef.current = [];
    transientHistoryOrderRef.current = [];
    transientHistoryThreadIdRef.current = null;
    summarizedRef.current = new Set<string>();
    pendingUsageBaselineMessageIdsRef.current = new Set();
    setPendingSupersededRunIds(new Set());
    setPendingSupersededMessageIds(new Set());
    prevHumanMsgCountRef.current =
      latestMessageCountsRef.current.humanMessageCount;
  }, [threadId]);

  // Release entries individually once canonical history confirms their stable
  // identities. Keep unconfirmed entries across failure/refetch within this
  // page lifecycle so a temporary persistence gap cannot hide a turn.
  useEffect(() => {
    transientHistoryBridgeRef.current = pruneConfirmedTransientMessages(
      transientHistoryBridgeRef.current,
      visibleHistory,
    );
    if (transientHistoryBridgeRef.current.length === 0) {
      transientHistoryOrderRef.current = [];
      transientHistoryThreadIdRef.current = null;
    }
  }, [visibleHistory]);

  useEffect(() => {
    if (optimisticThreadId && optimisticThreadId !== currentViewThreadId) {
      setOptimisticMessages([]);
      setOptimisticThreadId(null);
    }
    if (liveMessagesThreadId && liveMessagesThreadId !== currentViewThreadId) {
      setLiveMessagesThreadId(null);
    }
  }, [currentViewThreadId, liveMessagesThreadId, optimisticThreadId]);

  // When streaming starts without a baseline (e.g. reconnection, run started
  // from another client, or page reload mid-stream), snapshot the current
  // messages so only *new* messages are treated as "pending" for token usage.
  useEffect(() => {
    if (
      thread.isLoading &&
      pendingUsageBaselineMessageIdsRef.current.size === 0
    ) {
      pendingUsageBaselineMessageIdsRef.current = new Set(
        persistedMessages
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
    }
  }, [persistedMessages, thread.isLoading]);

  // Clear optimistic when server messages arrive.
  // For messages with a human optimistic message, wait until the server's
  // human message has arrived to avoid clearing before the input message
  // appears in the stream (the input message may arrive via "values" events
  // after individual "messages-tuple" events for AI messages).
  const optimisticMessageCount = optimisticMessages.length;
  const hasHumanOptimistic = optimisticMessages.some((m) => m.type === "human");
  useEffect(() => {
    if (optimisticMessageCount === 0) return;

    const newHumanMsgArrived = humanMessageCount > prevHumanMsgCountRef.current;

    if (!hasHumanOptimistic || newHumanMsgArrived) {
      setOptimisticMessages([]);
      setOptimisticThreadId(null);
    }
  }, [hasHumanOptimistic, humanMessageCount, optimisticMessageCount]);

  const sendMessage = useCallback(
    async (
      threadId: string,
      message: PromptInputMessage,
      extraContext?: Record<string, unknown>,
      options?: SendMessageOptions,
    ) => {
      if (sendInFlightRef.current) {
        return;
      }
      sendInFlightRef.current = true;

      // The send has genuinely proceeded past the in-flight guard, so callers
      // can now run one-time cleanup that must not fire on the dropped path.
      options?.onSent?.();

      const text = message.text.trim();

      // Capture the current human message count before showing optimistic
      // messages so we can wait for the server's copy of the user input.
      prevHumanMsgCountRef.current = humanMessageCount;
      pendingUsageBaselineMessageIdsRef.current = new Set(
        persistedMessages
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );

      // Build optimistic files list with uploading status
      const optimisticFiles: FileInMessage[] = (message.files ?? []).map(
        (f) => ({
          filename: f.filename ?? "",
          size: 0,
          status: "uploading" as const,
        }),
      );

      const hideFromUI = options?.additionalKwargs?.hide_from_ui === true;
      const optimisticAdditionalKwargs = {
        ...options?.additionalKwargs,
        ...(optimisticFiles.length > 0 ? { files: optimisticFiles } : {}),
      };

      const newOptimistic: Message[] = [];
      if (!hideFromUI) {
        newOptimistic.push({
          type: "human",
          id: `opt-human-${Date.now()}`,
          content: text ? [{ type: "text", text }] : "",
          additional_kwargs: optimisticAdditionalKwargs,
        });
      }

      if (optimisticFiles.length > 0 && !hideFromUI) {
        // Mock AI message while files are being uploaded
        newOptimistic.push({
          type: "ai",
          id: `opt-ai-${Date.now()}`,
          content: t.uploads.uploadingFiles,
          additional_kwargs: { element: "task" },
        });
      }
      setOptimisticThreadId(threadId);
      setLiveMessagesThreadId(threadId);
      setOptimisticMessages(newOptimistic);

      listeners.current.onSend?.(threadId);

      let uploadedFileInfo: UploadedFileInfo[] = [];

      try {
        // Upload files first if any
        if (message.files && message.files.length > 0) {
          setIsUploading(true);
          try {
            const filePromises = message.files.map((fileUIPart) =>
              promptInputFilePartToFile(fileUIPart),
            );

            const conversionResults = await Promise.all(filePromises);
            const files = conversionResults.filter(
              (file): file is File => file !== null,
            );
            const failedConversions = conversionResults.length - files.length;

            if (failedConversions > 0) {
              throw new Error(
                `Failed to prepare ${failedConversions} attachment(s) for upload. Please retry.`,
              );
            }

            if (!threadId) {
              throw new Error("Thread is not ready for file upload.");
            }

            if (files.length > 0) {
              const uploadResponse = await uploadFiles(threadId, files);
              uploadedFileInfo = uploadResponse.files;

              // Update optimistic human message with uploaded status + paths
              const uploadedFiles: FileInMessage[] = uploadedFileInfo.map(
                (info) => ({
                  filename: info.filename,
                  size: info.size,
                  path: info.virtual_path,
                  status: "uploaded" as const,
                }),
              );
              setOptimisticMessages((messages) => {
                if (messages.length > 1 && messages[0]) {
                  const humanMessage: Message = messages[0];
                  return [
                    {
                      ...humanMessage,
                      additional_kwargs: { files: uploadedFiles },
                    },
                    ...messages.slice(1),
                  ];
                }
                return messages;
              });
            }
          } catch (error) {
            const errorMessage =
              error instanceof Error
                ? error.message
                : "Failed to upload files.";
            toast.error(errorMessage);
            setOptimisticMessages([]);
            setOptimisticThreadId(null);
            setLiveMessagesThreadId(null);
            throw error;
          } finally {
            setIsUploading(false);
          }
        }

        // Build files metadata for submission (included in additional_kwargs)
        const filesForSubmit: FileInMessage[] = uploadedFileInfo.map(
          (info) => ({
            filename: info.filename,
            size: info.size,
            path: info.virtual_path,
            status: "uploaded" as const,
          }),
        );

        await thread.submit(
          {
            messages: buildThreadSubmitMessages({
              text,
              additionalKwargs: options?.additionalKwargs,
              additionalInputMessages: options?.additionalInputMessages,
              filesForSubmit,
            }),
          },
          {
            threadId: threadId,
            streamSubgraphs: true,
            streamResumable: true,
            config: {
              recursion_limit: 1000,
            },
            context: {
              ...extraContext,
              ...context,
              thinking_enabled: context.mode !== "flash",
              is_plan_mode: context.mode === "pro" || context.mode === "ultra",
              subagent_enabled: context.mode === "ultra",
              reasoning_effort:
                context.reasoning_effort ??
                (context.mode === "ultra"
                  ? "high"
                  : context.mode === "pro"
                    ? "medium"
                    : context.mode === "thinking"
                      ? "low"
                      : undefined),
              thread_id: threadId,
            },
          },
        );
        void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
        void queryClient.invalidateQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        });
      } catch (error) {
        setOptimisticMessages([]);
        setOptimisticThreadId(null);
        setLiveMessagesThreadId(null);
        setIsUploading(false);
        throw error;
      } finally {
        sendInFlightRef.current = false;
      }
    },
    [
      thread,
      t.uploads.uploadingFiles,
      context,
      queryClient,
      humanMessageCount,
      persistedMessages,
    ],
  );

  const regenerateMessage = useCallback(
    async (
      threadId: string,
      messageId: string,
      supersededMessageIds: string[] = [messageId],
    ) => {
      if (sendInFlightRef.current || !threadId || !messageId) {
        return;
      }
      sendInFlightRef.current = true;
      prevHumanMsgCountRef.current = humanMessageCount;
      pendingUsageBaselineMessageIdsRef.current = new Set(
        persistedMessages
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
      setLiveMessagesThreadId(threadId);
      listeners.current.onSend?.(threadId);
      let preparedSupersededRunId: string | null = null;
      let preparedSupersededMessageIds: string[] = [];

      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
            threadId,
          )}/runs/regenerate/prepare`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            credentials: "include",
            body: JSON.stringify({ message_id: messageId }),
          },
        );
        if (!response.ok) {
          throw new Error(await readResponseErrorMessage(response));
        }
        const prepared = (await response.json()) as RegeneratePrepareResponse;
        preparedSupersededRunId = prepared.target_run_id;
        preparedSupersededMessageIds = supersededMessageIds;
        setPendingSupersededRunIds((current) => {
          const next = new Set(current);
          next.add(prepared.target_run_id);
          return next;
        });
        setPendingSupersededMessageIds((current) => {
          const next = new Set(current);
          for (const id of supersededMessageIds) {
            next.add(id);
          }
          return next;
        });

        await thread.submit(prepared.input, {
          threadId,
          checkpoint: prepared.checkpoint,
          metadata: prepared.metadata,
          streamSubgraphs: true,
          streamResumable: true,
          config: {
            recursion_limit: 1000,
          },
          context: {
            ...context,
            thinking_enabled: context.mode !== "flash",
            is_plan_mode: context.mode === "pro" || context.mode === "ultra",
            subagent_enabled: context.mode === "ultra",
            reasoning_effort:
              context.reasoning_effort ??
              (context.mode === "ultra"
                ? "high"
                : context.mode === "pro"
                  ? "medium"
                  : context.mode === "thinking"
                    ? "low"
                    : undefined),
            thread_id: threadId,
          },
        });
        void queryClient.invalidateQueries({ queryKey: ["thread", threadId] });
        void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
        void queryClient.invalidateQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        });
        void queryClient.invalidateQueries({
          queryKey: threadTokenUsageQueryKey(threadId),
        });
      } catch (error) {
        setLiveMessagesThreadId(null);
        if (preparedSupersededRunId) {
          const supersededRunId = preparedSupersededRunId;
          setPendingSupersededRunIds((current) =>
            removeSetItems(current, [supersededRunId]),
          );
          setPendingSupersededMessageIds((current) =>
            removeSetItems(current, preparedSupersededMessageIds),
          );
        }
        toast.error(getStreamErrorMessage(error));
      } finally {
        sendInFlightRef.current = false;
      }
    },
    [context, humanMessageCount, persistedMessages, queryClient, thread],
  );

  // Cache the latest thread messages in a ref to compare against incoming history messages for deduplication,
  // and to allow access to the full message list in onUpdateEvent without causing re-renders.
  if (persistedMessages.length >= messagesRef.current.length) {
    messagesRef.current = persistedMessages;
  }

  const visibleOptimisticMessages = getVisibleOptimisticMessages(
    optimisticThreadId === currentViewThreadId ? optimisticMessages : [],
    prevHumanMsgCountRef.current,
    humanMessageCount,
  );

  const transientHistoryOrder =
    transientHistoryBridgeRef.current.length > 0 &&
    transientHistoryThreadIdRef.current === threadId
      ? mergeTransientHistoryBridgeOrder(
          transientHistoryOrderRef.current,
          persistedMessages,
        )
      : transientHistoryOrderRef.current;

  // Commit the extended non-rendering order skeleton after React commits this
  // render. The local value above keeps this render correctly anchored without
  // mutating a ref during render.
  useEffect(() => {
    if (
      transientHistoryBridgeRef.current.length > 0 &&
      transientHistoryThreadIdRef.current === threadId
    ) {
      transientHistoryOrderRef.current = mergeTransientHistoryBridgeOrder(
        transientHistoryOrderRef.current,
        persistedMessages,
      );
    }
  }, [persistedMessages, threadId]);

  const effectiveHistory = resolveThreadTransientHistoryBridge(
    visibleHistory,
    transientHistoryBridgeRef.current,
    transientHistoryThreadIdRef.current,
    threadId,
    transientHistoryOrder,
  );
  const mergedMessages = mergeMessages(
    effectiveHistory,
    persistedMessages,
    visibleOptimisticMessages,
  );
  const pendingUsageMessages = thread.isLoading
    ? getMessagesAfterBaseline(
        persistedMessages,
        pendingUsageBaselineMessageIdsRef.current,
      )
    : [];

  // Merge history, live stream, and optimistic messages for display
  // History messages may overlap with thread.messages; thread.messages take precedence
  const mergedThread = {
    ...thread,
    stop: stopThread,
    values: hasVisibleStreamState ? thread.values : EMPTY_THREAD_VALUES,
    messages: mergedMessages,
  } as typeof thread;

  return {
    thread: mergedThread,
    pendingUsageMessages,
    sendMessage,
    regenerateMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } as const;
}

type ThreadHistoryOptions = {
  enabled?: boolean;
  pendingSupersededRunIds?: ReadonlySet<string>;
};

export function useThreadHistory(
  threadId: string,
  { enabled = true, pendingSupersededRunIds }: ThreadHistoryOptions = {},
) {
  const historyQuery = useInfiniteQuery<
    ThreadMessagesPageResponse,
    Error,
    InfiniteData<ThreadMessagesPageResponse>,
    ReturnType<typeof threadHistoryQueryKey>,
    number | null
  >({
    queryKey: threadHistoryQueryKey(threadId),
    enabled: enabled && Boolean(threadId),
    initialPageParam: null,
    queryFn: async ({ pageParam, signal }) => {
      const url = buildThreadMessagesPageUrl(
        getBackendBaseURL(),
        threadId,
        pageParam ?? undefined,
      );
      const response = await fetch(url, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        signal,
      });
      if (!response.ok) {
        throw new Error(
          await readResponseErrorMessage(
            response,
            "Failed to load thread history.",
          ),
        );
      }
      return (await response.json()) as ThreadMessagesPageResponse;
    },
    getNextPageParam: getThreadHistoryNextPageParam,
  });

  const messageRows = useMemo(
    () => flattenThreadHistoryPages(historyQuery.data?.pages ?? []),
    [historyQuery.data?.pages],
  );

  const messages = useMemo(() => {
    return buildVisibleHistoryMessages(
      messageRows,
      pendingSupersededRunIds ?? new Set<string>(),
    );
  }, [messageRows, pendingSupersededRunIds]);

  useEffect(() => {
    if (historyQuery.error) {
      console.error(historyQuery.error);
      toast.error("Failed to load thread history.");
    }
  }, [historyQuery.error]);

  return {
    messages,
    loading: historyQuery.isLoading || historyQuery.isFetchingNextPage,
    hasMore: Boolean(historyQuery.hasNextPage),
    loadMore: historyQuery.fetchNextPage,
  };
}

export function useThreads(
  params: ThreadSearchParams = DEFAULT_THREAD_SEARCH_PARAMS,
) {
  const apiClient = getAPIClient();
  return useQuery<AgentThread[]>({
    ...buildThreadsSearchQueryOptions(apiClient, params),
  });
}

export const INFINITE_THREADS_PAGE_SIZE = 50;

export const INFINITE_THREADS_QUERY_KEY_PREFIX = [
  "threads",
  "searchInfinite",
] as const;

const INFINITE_THREADS_NEXT_PAGE_PARAM = Symbol(
  "deerflow.infiniteThreads.nextPageParam",
);

type InfiniteThreadsParams = Omit<
  Parameters<ThreadsClient["search"]>[0],
  "limit" | "offset"
>;

type InfiniteThreadsSearchClient = {
  threads: {
    search: ThreadsClient["search"];
  };
};

type InfiniteThreadsPageWithNextParam = AgentThread[] & {
  [INFINITE_THREADS_NEXT_PAGE_PARAM]?: number;
};

function annotateInfiniteThreadsPage(
  page: AgentThread[],
  nextPageParam: number | undefined,
): AgentThread[] {
  if (nextPageParam !== undefined) {
    Reflect.set(page, INFINITE_THREADS_NEXT_PAGE_PARAM, nextPageParam);
  }
  return page;
}

export async function fetchInfiniteThreadsPage(
  apiClient: InfiniteThreadsSearchClient,
  params: InfiniteThreadsParams,
  pageParam: number,
  pageSize: number = INFINITE_THREADS_PAGE_SIZE,
): Promise<AgentThread[]> {
  const threads: AgentThread[] = [];
  let offset = pageParam;
  let nextPageParam: number | undefined;

  while (threads.length < pageSize) {
    const currentLimit = pageSize - threads.length;
    const response = (await apiClient.threads.search<AgentThreadState>({
      ...params,
      limit: currentLimit,
      offset,
    })) as AgentThread[];

    threads.push(...filterThreadSearchResults(response, params));
    offset += response.length;

    if (response.length < currentLimit) {
      nextPageParam = undefined;
      break;
    }

    nextPageParam = offset;
  }

  return annotateInfiniteThreadsPage(threads, nextPageParam);
}

export function getInfiniteThreadsNextPageParam(
  lastPage: AgentThread[],
  allPages: AgentThread[][],
  pageSize: number = INFINITE_THREADS_PAGE_SIZE,
): number | undefined {
  const annotatedNextPageParam = Reflect.get(
    lastPage as InfiniteThreadsPageWithNextParam,
    INFINITE_THREADS_NEXT_PAGE_PARAM,
  );
  if (typeof annotatedNextPageParam === "number") {
    return annotatedNextPageParam;
  }

  if (lastPage.length < pageSize) {
    return undefined;
  }
  return allPages.reduce((sum, page) => sum + page.length, 0);
}

export function mapInfiniteThreadsCache(
  oldData: InfiniteData<AgentThread[]> | undefined,
  mapper: (thread: AgentThread) => AgentThread,
): InfiniteData<AgentThread[]> | undefined {
  if (!oldData) {
    return oldData;
  }
  return {
    ...oldData,
    pages: oldData.pages.map((page) => page.map(mapper)),
  };
}

export function filterInfiniteThreadsCache(
  oldData: InfiniteData<AgentThread[]> | undefined,
  predicate: (thread: AgentThread) => boolean,
): InfiniteData<AgentThread[]> | undefined {
  if (!oldData) {
    return oldData;
  }
  return {
    ...oldData,
    pages: oldData.pages.map((page) => page.filter(predicate)),
  };
}

export function useInfiniteThreads(
  params: InfiniteThreadsParams = {
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "updated_at", "values", "metadata"],
  },
) {
  const apiClient = getAPIClient();
  return useInfiniteQuery<
    AgentThread[],
    Error,
    InfiniteData<AgentThread[]>,
    readonly unknown[],
    number
  >({
    queryKey: [...INFINITE_THREADS_QUERY_KEY_PREFIX, params],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      fetchInfiniteThreadsPage(
        apiClient,
        params,
        pageParam,
        INFINITE_THREADS_PAGE_SIZE,
      ),
    getNextPageParam: (lastPage, allPages) =>
      getInfiniteThreadsNextPageParam(lastPage, allPages),
    refetchOnWindowFocus: false,
  });
}

export function useThreadRuns(
  threadId?: string,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const apiClient = getAPIClient();
  return useQuery<Run[]>({
    queryKey: ["thread", threadId],
    queryFn: async () => {
      if (!threadId) {
        return [];
      }
      const response = await apiClient.runs.list(threadId);
      return response;
    },
    enabled: enabled && Boolean(threadId),
    refetchOnWindowFocus: false,
  });
}

export function useThreadMetadata(
  threadId?: string | null,
  {
    enabled = true,
    isMock = false,
  }: { enabled?: boolean; isMock?: boolean } = {},
) {
  const apiClient = getAPIClient(isMock);
  return useQuery<AgentThread | null>({
    queryKey: ["thread", "metadata", threadId, isMock],
    queryFn: async () => {
      if (!threadId) {
        return null;
      }
      try {
        const response = await apiClient.threads.get(threadId);
        return response as AgentThread;
      } catch (error) {
        if (isThreadMissingError(error)) {
          return null;
        }
        throw error;
      }
    },
    enabled: enabled && Boolean(threadId),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useThreadTokenUsage(
  threadId?: string | null,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery<ThreadTokenUsageResponse | null>({
    queryKey: threadTokenUsageQueryKey(threadId),
    queryFn: async () => {
      if (!threadId) {
        return null;
      }
      return fetchThreadTokenUsage(threadId);
    },
    enabled: enabled && Boolean(threadId),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useBranchThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      messageId,
      messageIds,
      title,
    }: {
      threadId: string;
      messageId: string;
      messageIds?: string[];
      title?: string;
    }) => branchThreadFromTurn(threadId, { messageId, messageIds, title }),
    onSuccess(response, { threadId }) {
      void queryClient.invalidateQueries({
        queryKey: ["thread", "metadata", response.thread_id],
      });
      void queryClient.invalidateQueries({
        queryKey: ["thread", "metadata", threadId],
      });
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      void queryClient.invalidateQueries({
        queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      });
    },
  });
}

export function useRunDetail(threadId: string, runId: string) {
  const apiClient = getAPIClient();
  return useQuery<Run>({
    queryKey: ["thread", threadId, "run", runId],
    queryFn: async () => {
      const response = await apiClient.runs.get(threadId, runId);
      return response;
    },
    refetchOnWindowFocus: false,
  });
}

async function deleteLocalThreadData(threadId: string) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
    {
      method: "DELETE",
    },
  );

  // A 404 means the thread is already gone — the desired end state. The prior
  // `apiClient.threads.delete` call hits the same gateway handler (nginx
  // rewrites /api/langgraph/threads/* to /api/threads/*) and removes the
  // thread_meta row, so this second delete's ownership guard 404s. Treat it as
  // success to keep the delete idempotent.
  if (!response.ok && response.status !== 404) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to delete local thread data." }));
    throw new Error(error.detail ?? "Failed to delete local thread data.");
  }
}

async function deleteThreadEverywhere(
  apiClient: ThreadDeleteClient,
  threadId: string,
) {
  await apiClient.threads.delete(threadId);
  await deleteLocalThreadData(threadId);
}

export async function findSidecarThreadIdsForParent(
  apiClient: ThreadSidecarSearchClient,
  parentThreadId: string,
) {
  const threadIds: string[] = [];
  const limit = 100;
  let offset = 0;

  while (true) {
    const response = await apiClient.threads.search({
      metadata: {
        [SIDECAR_METADATA_KEY]: true,
        parent_thread_id: parentThreadId,
      },
      limit,
      offset,
      sortBy: "updated_at",
      sortOrder: "desc",
      select: ["thread_id", "metadata"],
    });

    for (const thread of response) {
      if (
        isSidecarThread(thread) &&
        thread.metadata?.parent_thread_id === parentThreadId
      ) {
        threadIds.push(thread.thread_id);
      }
    }

    if (response.length < limit) {
      break;
    }
    offset += response.length;
  }

  return threadIds;
}

async function deleteSidecarThreadsForParent(
  apiClient: ThreadDeleteClient,
  parentThreadId: string,
) {
  let sidecarThreadIds: string[];
  try {
    sidecarThreadIds = await findSidecarThreadIdsForParent(
      apiClient,
      parentThreadId,
    );
  } catch (err) {
    console.warn(
      `Failed to look up sidecar threads for parent ${parentThreadId}; skipping cascade cleanup. Orphaned sidecar threads may remain.`,
      err,
    );
    return [];
  }

  const results = await Promise.allSettled(
    sidecarThreadIds.map((threadId) =>
      deleteThreadEverywhere(apiClient, threadId),
    ),
  );

  const failedDeletions = results
    .map((result, index) =>
      result.status === "rejected"
        ? { threadId: sidecarThreadIds[index], reason: result.reason }
        : null,
    )
    .filter((entry): entry is { threadId: string; reason: unknown } =>
      Boolean(entry),
    );

  if (failedDeletions.length > 0) {
    console.warn(
      `Failed to delete ${failedDeletions.length} sidecar thread(s) for parent ${parentThreadId}; orphaned sidecar threads may remain.`,
      failedDeletions,
    );
  }

  return sidecarThreadIds.filter((_, index) => {
    return results[index]?.status === "fulfilled";
  });
}

export function useDeleteThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient() as ThreadDeleteClient;
  return useMutation({
    mutationFn: async ({
      threadId,
      onRemoteDeleted,
    }: {
      threadId: string;
      onRemoteDeleted?: () => void;
    }) => {
      const deletedSidecarThreadIds = await deleteSidecarThreadsForParent(
        apiClient,
        threadId,
      );
      await apiClient.threads.delete(threadId);
      onRemoteDeleted?.();
      await deleteLocalThreadData(threadId);
      return deletedSidecarThreadIds;
    },
    onSuccess(deletedSidecarThreadIds, { threadId }) {
      const deletedThreadIds = new Set([threadId, ...deletedSidecarThreadIds]);
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread> | undefined) => {
          if (oldData == null) {
            return oldData;
          }
          return oldData.filter((t) => !deletedThreadIds.has(t.thread_id));
        },
      );
      queryClient.setQueriesData(
        {
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
          exact: false,
        },
        (oldData: InfiniteData<AgentThread[]> | undefined) =>
          filterInfiniteThreadsCache(
            oldData,
            (t) => !deletedThreadIds.has(t.thread_id),
          ),
      );
    },

    onSettled() {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      void queryClient.invalidateQueries({
        queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      });
    },
  });
}

export function useRenameThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      title,
    }: {
      threadId: string;
      title: string;
    }) => {
      await apiClient.threads.updateState(threadId, {
        values: { title },
      });
    },
    onSuccess(_, { threadId, title }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread>) => {
          return oldData.map((t) => {
            if (t.thread_id === threadId) {
              return {
                ...t,
                values: {
                  ...t.values,
                  title,
                },
              };
            }
            return t;
          });
        },
      );
      queryClient.setQueriesData(
        {
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
          exact: false,
        },
        (oldData: InfiniteData<AgentThread[]> | undefined) =>
          mapInfiniteThreadsCache(oldData, (t) =>
            t.thread_id === threadId
              ? {
                  ...t,
                  values: {
                    ...t.values,
                    title,
                  },
                }
              : t,
          ),
      );
    },
  });
}
