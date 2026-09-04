import type { AIMessage, Message, Run } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  type QueryClient,
  type InfiniteData,
  type QueryFilters,
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
import { getMessageRunId } from "../messages/run-duration";
import {
  hasContent,
  hasToolCalls,
  isHiddenFromUIMessage,
} from "../messages/utils";
import type { FileInMessage } from "../messages/utils";
import type { LocalSettings } from "../settings";
import { isSidecarThread, SIDECAR_METADATA_KEY } from "../sidecar/thread";
import { useSubtaskContext, useUpdateSubtask } from "../tasks/context";
import { taskEventToSubtaskUpdate } from "../tasks/lifecycle";
import { messageToStep } from "../tasks/steps";
import type { UploadedFileInfo } from "../uploads";
import { promptInputFilePartToFile, uploadFiles } from "../uploads";

import {
  branchThreadFromTurn,
  fetchThreadTokenUsage,
  patchThreadMetadata,
  type ThreadMetadataPatch,
} from "./api";
import {
  hasRenderedThreadStateUpdate,
  reduceThreadStateUpdates,
} from "./stream-state";
import {
  buildThreadsSearchQueryOptions,
  DEFAULT_THREAD_SEARCH_PARAMS,
  filterThreadSearchResults,
  type ThreadSearchParams,
} from "./thread-search-query";
import {
  retainThreadTokenUsagePlaceholder,
  threadTokenUsageQueryKey,
} from "./token-usage";
import type {
  AgentThread,
  AgentThreadState,
  RunMessage,
  ThreadTokenUsageResponse,
} from "./types";
import { THREAD_PINNED_METADATA_KEY } from "./utils";

export type ThreadStreamOptions = {
  threadId?: string | null | undefined;
  displayThreadId?: string | null | undefined;
  context: LocalSettings["context"];
  isMock?: boolean;
  onSend?: (threadId: string) => void;
  onStart?: (threadId: string, runId: string) => void;
  onFinish?: (state: AgentThreadState) => void;
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

type EditRegeneratePrepareResponse = RegeneratePrepareResponse & {
  replacement_human_message_id: string;
  source_message_ids: string[];
};

export type PendingPreparedReplayMask = {
  kind: "regenerate" | "edit";
  targetRunId: string;
  supersededMessageIds: string[];
  replacementHumanMessageId?: string;
};

export function hasToolResult(messages: Message[], toolName: string): boolean {
  const matchingToolCallIds = new Set<string>();
  for (const message of messages) {
    if (message.type !== "ai") {
      continue;
    }
    for (const toolCall of message.tool_calls ?? []) {
      if (toolCall.name === toolName && toolCall.id) {
        matchingToolCallIds.add(toolCall.id);
      }
    }
  }

  return messages.some(
    (message) =>
      message.type === "tool" &&
      (message.name === toolName ||
        matchingToolCallIds.has(message.tool_call_id)),
  );
}

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

// Stable identity for "no optimistic messages" so the merged-messages memo
// below is not invalidated by a fresh empty array on every render.
const EMPTY_MESSAGES: Message[] = [];
const EMPTY_RUN_MESSAGES: RunMessage[] = [];
const EMPTY_MESSAGE_IDENTITIES: readonly string[] = [];
const INJECTED_USER_MESSAGE_ID_SUFFIX = "__user";
// Thread-global feed position, attached by the backend to history rows and to
// `values` frame messages it has already persisted. Mirrors MESSAGE_SEQ_KEY in
// `deerflow/runtime/events/message_identity.py`.
const MESSAGE_SEQ_KEY = "deerflow_seq";

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

/** Thread-global feed position, when the backend has attached one. */
function messageSeq(message: Message): number | undefined {
  const seq = message.additional_kwargs?.[MESSAGE_SEQ_KEY];
  return typeof seq === "number" ? seq : undefined;
}

function messageIdentity(message: Message): string | undefined {
  if (
    "tool_call_id" in message &&
    typeof message.tool_call_id === "string" &&
    message.tool_call_id.length > 0
  ) {
    return `tool:${message.tool_call_id}`;
  }
  if (typeof message.id === "string" && message.id.length > 0) {
    // DynamicContextMiddleware replaces the submitted HumanMessage(id=X) with
    // a hidden SystemMessage(id=X) and the real HumanMessage(id=X__user).
    // Treat those human copies as one UI message so a committed render ledger
    // cannot retain X beside the later checkpoint copy X__user.
    const messageId =
      message.type === "human" &&
      message.id.endsWith(INJECTED_USER_MESSAGE_ID_SUFFIX)
        ? message.id.slice(0, -INJECTED_USER_MESSAGE_ID_SUFFIX.length) ||
          message.id
        : message.id;
    return `message:${messageId}`;
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
    // seq rides along for the same reason: it is the thread-global position
    // this feed is ordered by, and merging needs it on the message itself to
    // place a checkpoint copy that falls outside the loaded window (#4666).
    ...visibleRows.map((message) => ({
      ...message.content,
      run_id: message.run_id,
      additional_kwargs: {
        ...message.content.additional_kwargs,
        [MESSAGE_SEQ_KEY]: message.seq,
      },
    })),
  ]);
}

export type ThreadMessagesPageResponse = {
  data: RunMessage[];
  has_more: boolean;
  next_before_seq: number | null;
};

function isValidThreadMessageSeq(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

/**
 * Validate the sequence fields that history reconciliation and pagination use
 * as runtime identities. The static RunMessage type cannot protect this JSON
 * boundary from version skew or malformed responses.
 */
export function parseThreadMessagesPageResponse(
  value: unknown,
): ThreadMessagesPageResponse {
  if (typeof value !== "object" || value === null) {
    throw new Error("Thread history returned an invalid response.");
  }

  const data = Reflect.get(value, "data");
  const hasMore = Reflect.get(value, "has_more");
  const nextBeforeSeq = Reflect.get(value, "next_before_seq");
  if (!Array.isArray(data) || typeof hasMore !== "boolean") {
    throw new Error("Thread history returned an invalid response.");
  }

  const seenSeqs = new Set<number>();
  for (const row of data) {
    const seq =
      typeof row === "object" && row !== null
        ? Reflect.get(row, "seq")
        : undefined;
    if (!isValidThreadMessageSeq(seq)) {
      throw new Error("Thread history returned a row with an invalid seq.");
    }
    if (seenSeqs.has(seq)) {
      throw new Error("Thread history returned duplicate seq values.");
    }
    seenSeqs.add(seq);
  }

  if (
    (hasMore && !isValidThreadMessageSeq(nextBeforeSeq)) ||
    (!hasMore && nextBeforeSeq !== null)
  ) {
    throw new Error(
      "Thread history returned an invalid next_before_seq cursor.",
    );
  }

  return value as ThreadMessagesPageResponse;
}

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

/**
 * Preserve rows that this client has already loaded while newest-first cursor
 * pages move forward during a long run.
 *
 * A background refetch recalculates every loaded page from the refreshed first
 * page. When older pages have not all been loaded yet, that can displace rows
 * which were visible a moment ago even though they still exist on the server.
 * Thread-global seq is the authoritative order; refreshed copies win without
 * moving their established position.
 */
export function reconcileThreadHistoryRows(
  previousRows: RunMessage[],
  currentRows: RunMessage[],
  isAuthoritativeComplete: boolean,
): RunMessage[] {
  const sourceRows = isAuthoritativeComplete
    ? currentRows
    : [...previousRows, ...currentRows];
  if (sourceRows.some((row) => !isValidThreadMessageSeq(row.seq))) {
    console.error(
      "Thread history reconciliation received an invalid sequence value.",
    );
    // Never skip an invalid row or feed it into Map/Array.sort: either choice
    // can silently lose or misorder messages. A failed refresh keeps the last
    // known-good snapshot; an invalid first snapshot degrades to server order.
    return previousRows.length > 0 ? previousRows : currentRows;
  }

  const rowsBySeq = new Map<number, RunMessage>();
  for (const row of sourceRows) {
    rowsBySeq.set(row.seq, row);
  }

  const reconciled = dedupeRunMessagesByIdentity(
    [...rowsBySeq.values()].sort((left, right) => left.seq - right.seq),
  );
  if (
    reconciled.length === previousRows.length &&
    reconciled.every((row, index) => row === previousRows[index])
  ) {
    return previousRows;
  }
  return reconciled;
}

export function mergeMessages(
  historyMessages: Message[],
  threadMessages: Message[],
  optimisticMessages: Message[],
): Message[] {
  const savedTurnDurations = new Map<string, number>();
  const savedRunIds = new Map<string, string>();
  for (const msg of historyMessages) {
    const identity = messageIdentity(msg);
    const runId = getMessageRunId(msg);
    if (identity && runId) {
      savedRunIds.set(identity, runId);
    }
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

  // Lower bound of the history page window that is currently loaded. A live
  // message whose seq is below it belongs before everything on screen, which
  // is knowledge the anchor weaving below cannot reach: the anchor only says
  // "earlier than this row", and after compaction the nearest anchor can sit
  // deep inside the window (#4666 — measured at row 25 of 50).
  const canonicalMinSeq = canonical.reduce<number | undefined>(
    (min, message) => {
      const seq = messageSeq(message);
      return seq !== undefined && (min === undefined || seq < min) ? seq : min;
    },
    undefined,
  );
  const beforeWindow: Message[] = [];

  // Split off what the feed places before the loaded window BEFORE the anchor
  // walk rather than inside it. A summarized checkpoint can share no identity
  // at all with the loaded page — compaction keeps only this run's recent tail,
  // while the page on screen was fetched turns earlier — and the anchor loop
  // then never runs. That is exactly when a rescued early turn most needs its
  // seq: user submits, waits without reloading, compaction fires, and the
  // message is appended to the tail instead (#4666).
  const liveInWindow: Message[] = [];
  for (const message of live) {
    const seq = messageSeq(message);
    if (
      seq !== undefined &&
      canonicalMinSeq !== undefined &&
      seq < canonicalMinSeq
    ) {
      beforeWindow.push(message);
    } else {
      liveInWindow.push(message);
    }
  }

  // A summarized checkpoint is not necessarily a contiguous history suffix:
  // middleware may retain protected prompt/input messages at the front and a
  // recent tail at the back. Treat every shared identity as an ordering anchor,
  // replacing the canonical copy in place. New live messages are woven before
  // the next shared anchor (or after the last one), so a protected early input
  // can never be moved to the tail by global last-copy deduplication.
  for (const message of liveInWindow) {
    const identity = messageIdentity(message);
    const canonicalMessage = identity
      ? canonicalByIdentity.get(identity)
      : undefined;
    if (!identity || !canonicalMessage) {
      pending.push(message);
      continue;
    }

    // A summarized checkpoint may start with a protected message whose true
    // canonical position is separated from this anchor by unloaded pages —
    // rescued dynamic-context messages are the common case. Its position
    // relative to this anchor is still known (both the checkpoint and
    // seq-sorted history place it earlier), so it is woven in before the
    // anchor like any other live-only segment. Dropping it instead was how a
    // user's own question disappeared from a long thread once the first
    // history page no longer reached back to it (#4666): a collapsed unloaded
    // gap is recoverable by paging, a discarded message is not.
    if (pending.length > 0) {
      beforeAnchor.set(identity, [
        ...(beforeAnchor.get(identity) ?? []),
        ...pending,
      ]);
    }
    pending = [];
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
    canonicalAndLive = [...canonical, ...liveInWindow];
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
    ...[...beforeWindow].sort(
      (left, right) => (messageSeq(left) ?? 0) - (messageSeq(right) ?? 0),
    ),
    ...canonicalAndLive,
    ...optimisticMessages,
  ]);

  return merged.map((message) => {
    const identity = messageIdentity(message);
    if (!identity) {
      return message;
    }
    const shouldRestoreRunId =
      savedRunIds.has(identity) && !getMessageRunId(message);
    const shouldRestoreTurnDuration =
      savedTurnDurations.has(identity) &&
      message.additional_kwargs?.turn_duration === undefined;
    if (shouldRestoreRunId || shouldRestoreTurnDuration) {
      return {
        ...message,
        ...(shouldRestoreRunId ? { run_id: savedRunIds.get(identity) } : {}),
        ...(shouldRestoreTurnDuration
          ? {
              additional_kwargs: {
                ...message.additional_kwargs,
                turn_duration: savedTurnDurations.get(identity),
              },
            }
          : {}),
      } as Message;
    }
    return message;
  });
}

/**
 * Keep messages from a locally submitted turn behind that turn's user input.
 * LangGraph `messages-tuple` events can publish the first AI/tool steps before
 * canonical history contains the user message. Those steps are not part of the
 * pre-submit baseline, so move only that visible pending segment behind the
 * first new human message without disturbing established history or hidden
 * checkpoint controls. The caller keeps the baseline after stream completion
 * because the SDK may retain its transient event order until the next submit.
 */
export function restoreLocalTurnMessageOrder(
  messages: Message[],
  baselineMessageIdentities: ReadonlySet<string>,
): Message[] {
  const pendingHumanIndex = messages.findIndex((message) => {
    const identity = messageIdentity(message);
    return (
      message.type === "human" &&
      !isHiddenFromUIMessage(message) &&
      identity !== undefined &&
      !baselineMessageIdentities.has(identity)
    );
  });
  if (pendingHumanIndex <= 0) {
    return messages;
  }

  const stablePrefix: Message[] = [];
  const earlyPendingSteps: Message[] = [];
  for (const message of messages.slice(0, pendingHumanIndex)) {
    const identity = messageIdentity(message);
    const isVisiblePendingStep =
      (message.type === "ai" || message.type === "tool") &&
      !isHiddenFromUIMessage(message) &&
      identity !== undefined &&
      !baselineMessageIdentities.has(identity);
    if (isVisiblePendingStep) {
      earlyPendingSteps.push(message);
    } else {
      stablePrefix.push(message);
    }
  }
  if (earlyPendingSteps.length === 0) {
    return messages;
  }

  return [
    ...stablePrefix,
    messages[pendingHumanIndex]!,
    ...earlyPendingSteps,
    ...messages.slice(pendingHumanIndex + 1),
  ];
}

/**
 * Reconnect/reload counterpart of {@link restoreLocalTurnMessageOrder}.
 *
 * After a mid-run page reload the local-turn baseline is empty, so the local
 * restore never runs — yet the same ordering race still applies: replayed
 * `messages-tuple` steps can reach the merged list before the turn's human
 * message (the retained replay buffer may even have dropped it), and the
 * live-only human is then woven in before the next shared history anchor,
 * leaving steps of the SAME run above the user message they belong to.
 *
 * Canonical history is seq-sorted, so a visible AI/tool step sitting above
 * the last visible human while another message of the same run sits below it
 * (a "same-run sandwich") is provably misplaced. Run_id-less steps are
 * live-only (history rows always carry run_id) and are attributable to the
 * reconnected run only when a run_id-less step also follows the human.
 *
 * Only steps after the last terminal assistant answer (visible content, no
 * tool calls) in the segment are candidates: such an answer completes the
 * turn that owns it, so everything up to it belongs to a finished turn and
 * must keep its position even when run_ids are absent or uniform across
 * turns (branch-seeded history, mocked feeds). A still-streaming text step
 * can look like a terminal answer before its tool call arrives (#4304); it
 * then stays above the human until canonical history heals the order — an
 * accepted transient, far safer than pulling a completed turn's answer
 * below the next user message. A resent turn after an interrupted run and
 * pagination orphans from older turns (#4399) fail the checks as well and
 * are left untouched. When an interrupted turn and the next turn share one
 * synthetic run_id, the previous human anchor plus the missing terminal
 * answer makes step ownership ambiguous, so that layout is also preserved.
 */
export function restoreReconnectedTurnMessageOrder(
  messages: Message[],
): Message[] {
  let humanIndex = -1;
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index];
    if (message?.type === "human" && !isHiddenFromUIMessage(message)) {
      humanIndex = index;
      break;
    }
  }
  if (humanIndex <= 0) {
    return messages;
  }

  // Only the segment since the previous visible human can belong to the
  // active turn; older turns are anchored by their own human message.
  let segmentStart = 0;
  for (let index = humanIndex - 1; index >= 0; index--) {
    const message = messages[index];
    if (message?.type === "human" && !isHiddenFromUIMessage(message)) {
      segmentStart = index + 1;
      break;
    }
  }
  if (segmentStart >= humanIndex) {
    return messages;
  }

  // A terminal assistant answer completes the turn that owns it. Only steps
  // after the last such boundary can belong to the active turn.
  let candidateStart = segmentStart;
  for (let index = segmentStart; index < humanIndex; index++) {
    const message = messages[index]!;
    if (
      message.type === "ai" &&
      !isHiddenFromUIMessage(message) &&
      hasContent(message) &&
      !hasToolCalls(message)
    ) {
      candidateStart = index + 1;
    }
  }

  const previousHumanRunId =
    segmentStart > 0 ? getMessageRunId(messages[segmentStart - 1]!) : undefined;
  const hasUniformRunIdSincePreviousHuman =
    previousHumanRunId !== undefined &&
    messages
      .slice(segmentStart - 1)
      .every(
        (message) =>
          isHiddenFromUIMessage(message) ||
          getMessageRunId(message) === previousHumanRunId,
      );
  if (candidateStart === segmentStart && hasUniformRunIdSincePreviousHuman) {
    return messages;
  }

  const runIdsAfter = new Set<string>();
  let hasLiveOnlyStepAfter = false;
  for (const message of messages.slice(humanIndex + 1)) {
    const runId = getMessageRunId(message);
    if (runId) {
      runIdsAfter.add(runId);
    } else if (
      (message.type === "ai" || message.type === "tool") &&
      !isHiddenFromUIMessage(message)
    ) {
      hasLiveOnlyStepAfter = true;
    }
  }

  const misplacedSteps: Message[] = [];
  const stablePrefix = messages.slice(0, candidateStart);
  for (const message of messages.slice(candidateStart, humanIndex)) {
    const isVisibleStep =
      (message.type === "ai" || message.type === "tool") &&
      !isHiddenFromUIMessage(message);
    const runId = getMessageRunId(message);
    if (
      isVisibleStep &&
      ((runId !== undefined && runIdsAfter.has(runId)) ||
        (runId === undefined && hasLiveOnlyStepAfter))
    ) {
      misplacedSteps.push(message);
    } else {
      stablePrefix.push(message);
    }
  }
  if (misplacedSteps.length === 0) {
    return messages;
  }

  return [
    ...stablePrefix,
    messages[humanIndex]!,
    ...misplacedSteps,
    ...messages.slice(humanIndex + 1),
  ];
}

/**
 * Keep a run-scoped ledger of every visible message that reached a committed
 * UI frame. Live checkpoint windows can roll forward between two
 * summarization events; replacing this ledger with only the newest window
 * would make the intervening steps impossible to rescue at the next
 * RemoveMessage(ALL).
 *
 * The newest visible copy wins by identity without moving its established
 * position. Explicitly superseded messages are removed so regeneration cannot
 * revive an answer that the UI intentionally hid.
 */
export function mergeRenderedMessageLedger(
  previouslyRenderedMessages: Message[],
  visibleMessages: Message[],
  supersededMessageIds: ReadonlySet<string> = new Set<string>(),
): Message[] {
  const isEligible = (message: Message) =>
    messageIdentity(message) !== undefined &&
    (!message.id || !supersededMessageIds.has(message.id));
  const retainedPrevious =
    supersededMessageIds.size === 0
      ? previouslyRenderedMessages.filter(
          (message) => messageIdentity(message) !== undefined,
        )
      : previouslyRenderedMessages.filter(isEligible);
  const eligibleVisibleMessages = visibleMessages.filter(isEligible);
  if (retainedPrevious.length === 0) {
    return eligibleVisibleMessages;
  }
  return mergeMessages(retainedPrevious, eligibleVisibleMessages, []);
}

/**
 * Derive the live turns that context summarization is about to drop and that
 * therefore need a short-lived visual bridge until run-event history catches up.
 *
 * Summarization emits `RemoveMessage(ALL)` + a hidden summary + the retained
 * tail. Everything in the current live thread that is absent from the retained
 * visible window is being removed; we keep those (minus the summary control
 * messages already tracked) so the UI can still show the full conversation
 * (#3825). Comparing identities instead of slicing at the first retained
 * message also handles a protected early input followed by a recent tail.
 */
export function computeSummarizationTransientMessages(
  currentMessages: Message[],
  summarizationMessages: Message[],
  summarizedMessageIds: ReadonlySet<string>,
  previouslyRenderedMessages: Message[] = EMPTY_MESSAGES,
): Message[] {
  const retainedVisibleIdentities = new Set(
    summarizationMessages
      .filter((message) => message.type !== "remove")
      .filter((message) => !isHiddenFromUIMessage(message))
      .map(messageIdentity)
      .filter(isNonEmptyString),
  );

  // Updates can outrun React while the SDK applies RemoveMessage(ALL). In that
  // case currentMessages may already be the retained post-compaction window
  // even though the previous committed UI frame still showed the removed
  // processing steps. Use that frame as the chronological base, then overlay
  // fresher live copies. This rescues only messages the user actually saw and
  // preserves the unloaded-history-gap protection in the bridge resolver.
  const captureMessages =
    previouslyRenderedMessages.length > 0
      ? mergeMessages(previouslyRenderedMessages, currentMessages, [])
      : currentMessages;
  const moved: Message[] = [];
  for (const message of captureMessages) {
    const identity = messageIdentity(message);
    if (identity && retainedVisibleIdentities.has(identity)) {
      continue;
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
  previouslyRenderedOrder: readonly string[] = EMPTY_MESSAGE_IDENTITIES,
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
  const previouslyRenderedIndex = new Map(
    previouslyRenderedOrder.map((identity, index) => [identity, index]),
  );
  let pending: Message[] = [];
  let lastAnchorIdentity: string | undefined;
  let hasCanonicalAnchor = false;

  for (const identity of bridgeOrder) {
    if (presentIdentities.has(identity)) {
      if (pending.length > 0) {
        if (hasCanonicalAnchor) {
          beforeAnchor.set(identity, [
            ...(beforeAnchor.get(identity) ?? []),
            ...pending,
          ]);
        } else {
          const anchorRenderIndex = previouslyRenderedIndex.get(identity);
          if (anchorRenderIndex !== undefined) {
            const safeRenderedPrefix = pending
              .filter((message) => {
                const pendingIdentity = messageIdentity(message);
                const renderIndex = pendingIdentity
                  ? previouslyRenderedIndex.get(pendingIdentity)
                  : undefined;
                return (
                  renderIndex !== undefined && renderIndex < anchorRenderIndex
                );
              })
              .sort((left, right) => {
                const leftIndex =
                  previouslyRenderedIndex.get(messageIdentity(left) ?? "") ??
                  Number.MAX_SAFE_INTEGER;
                const rightIndex =
                  previouslyRenderedIndex.get(messageIdentity(right) ?? "") ??
                  Number.MAX_SAFE_INTEGER;
                return leftIndex - rightIndex;
              });
            if (safeRenderedPrefix.length > 0) {
              beforeAnchor.set(identity, safeRenderedPrefix);
            }
          }
        }
      }
      // The prefix before the first loaded anchor has no trustworthy position:
      // cursor pages containing its intervening history may not be loaded yet.
      // The sole exception is a prefix whose exact relative position was
      // already committed to the previous UI frame.
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
): readonly string[] {
  const capturedOrder = dedupeMessagesByIdentity(capturedMessages)
    .map(messageIdentity)
    .filter(isNonEmptyString);
  // Clone lazily and return the input when nothing is appended: this runs per
  // render while the bridge is active, and a fresh array would invalidate the
  // coalesced render memo on every chunk (#4409 Phase 1).
  let merged: string[] | null = null;
  const seen = new Set(currentOrder);
  for (const identity of capturedOrder) {
    if (!seen.has(identity)) {
      seen.add(identity);
      (merged ??= [...currentOrder]).push(identity);
    }
  }
  return merged ?? currentOrder;
}

export function resolveThreadTransientHistoryBridge(
  visibleHistory: Message[],
  transientMessages: Message[],
  bridgeThreadId: string | null,
  currentThreadId: string | null | undefined,
  bridgeOrder?: readonly string[],
  previouslyRenderedOrder?: readonly string[],
): Message[] {
  if (!bridgeThreadId || bridgeThreadId !== currentThreadId) {
    return visibleHistory;
  }
  return resolveTransientHistoryBridge(
    visibleHistory,
    transientMessages,
    bridgeOrder,
    previouslyRenderedOrder,
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

/**
 * Human-message baseline for a prepared replay (regenerate / edit).
 *
 * A replay masks the turn it supersedes, so those messages leave the live
 * message list the moment the mask is applied. Baselining on the pre-mask count
 * means the replacement only ever restores the count instead of exceeding it,
 * and the optimistic copy is never recognised as confirmed. That matters for
 * the first turn of a thread, where the runtime re-keys the replacement message
 * so identity comparison cannot stand in for the count either.
 */
export function countHumanMessagesExcludingSuperseded(
  messages: Message[],
  supersededMessageIds: readonly string[],
): number {
  const superseded = new Set(supersededMessageIds);
  return messages.filter(
    (message) =>
      message.type === "human" && (!message.id || !superseded.has(message.id)),
  ).length;
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

export function areOptimisticMessagesConfirmed(
  optimisticMessages: Message[],
  persistedMessages: Message[],
): boolean {
  const optimisticIdentities = optimisticMessages
    .map(messageIdentity)
    .filter(isNonEmptyString);
  if (optimisticIdentities.length === 0) {
    return false;
  }
  const persistedIdentities = new Set(
    persistedMessages.map(messageIdentity).filter(isNonEmptyString),
  );
  return optimisticIdentities.every((identity) =>
    persistedIdentities.has(identity),
  );
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

export const STREAM_RENDER_COALESCE_MS = 80;

export type CoalesceDecision =
  | { action: "flush-now" }
  | { action: "schedule"; delayMs: number }
  | { action: "wait" };

/**
 * Decide how an incoming stream update reaches the rendered snapshot: flush
 * immediately once a full interval has elapsed (leading edge), otherwise
 * schedule exactly one trailing flush for the interval remainder. Unlike a
 * debounce, the delay never extends past the interval, so a dense stream can
 * never starve rendering.
 */
export function decideCoalesce(
  nowMs: number,
  lastFlushMs: number,
  intervalMs: number,
  hasPendingTimer: boolean,
): CoalesceDecision {
  if (nowMs - lastFlushMs >= intervalMs) {
    return { action: "flush-now" };
  }
  if (hasPendingTimer) {
    return { action: "wait" };
  }
  return { action: "schedule", delayMs: intervalMs - (nowMs - lastFlushMs) };
}

/**
 * While a run is streaming, expose the messages array as a snapshot that
 * updates at most once per interval instead of once per SSE chunk, so the
 * merge/group/render pipeline runs per frame budget rather than per token
 * (#4409 Phase 1). When the stream is idle the latest array passes straight
 * through, keeping non-stream updates immediate.
 */
function sameMessageArray(a: Message[], b: Message[]): boolean {
  return (
    a === b ||
    (a.length === b.length && a.every((message, index) => message === b[index]))
  );
}

export function useCoalescedStreamMessages(
  messages: Message[],
  isStreaming: boolean,
  intervalMs: number = STREAM_RENDER_COALESCE_MS,
): Message[] {
  // `null` means "no snapshot belongs to the current stream": the live array is
  // returned until the leading-edge flush lands, so a snapshot left over from an
  // earlier stream can never be painted. This hook outlives thread switches (the
  // chat page deliberately avoids re-mounting, see its `onStart` comment), so a
  // retained snapshot would otherwise be another thread's messages.
  const [snapshot, setSnapshot] = useState<Message[] | null>(null);
  const latestRef = useRef(messages);
  latestRef.current = messages;
  // Monotonic clock: a wall-clock step (NTP, sleep/wake) between two reads
  // would otherwise be added to the remaining interval and stall the flush for
  // the length of the jump. -Infinity means "never flushed", so the first
  // update of a stream always takes the leading edge.
  const lastFlushRef = useRef(Number.NEGATIVE_INFINITY);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Every publication goes through the shallow-equality guard: inputs whose
  // identity churns without content change (the SDK getter mints fresh arrays)
  // must not re-trigger renders, or this effect would setState-loop.
  const publish = useCallback(() => {
    setSnapshot((previous) =>
      previous !== null && sameMessageArray(previous, latestRef.current)
        ? previous
        : latestRef.current,
    );
  }, []);

  const clearPendingFlush = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!isStreaming) {
      clearPendingFlush();
      // Drop the flush baseline so the leading edge is per stream rather than
      // per hook instance: a run starting within one interval of the previous
      // one must not have its first frame deferred. Dropping the snapshot with
      // it costs one render per stream end, versus one per idle message change
      // if the snapshot were instead kept in sync while nothing reads it.
      lastFlushRef.current = Number.NEGATIVE_INFINITY;
      setSnapshot((previous) => (previous === null ? previous : null));
      return;
    }
    const now = performance.now();
    const decision = decideCoalesce(
      now,
      lastFlushRef.current,
      intervalMs,
      timerRef.current !== null,
    );
    if (decision.action === "flush-now") {
      // A trailing timer can still be armed here: timers fire late under
      // main-thread load, which is exactly when a chunk overtakes one. Leaving
      // it would publish a second time and slip the next interval forward.
      clearPendingFlush();
      lastFlushRef.current = now;
      publish();
    } else if (decision.action === "schedule") {
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        // Read the clock again: timers fire late under load, and the next
        // interval must start from the real flush.
        lastFlushRef.current = performance.now();
        publish();
      }, decision.delayMs);
    }
  }, [messages, isStreaming, intervalMs, publish, clearPendingFlush]);

  useEffect(
    () => () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    },
    [],
  );

  return isStreaming && snapshot !== null ? snapshot : messages;
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
  const pendingPreparedReplayRef = useRef<PendingPreparedReplayMask | null>(
    null,
  );
  const listeners = useRef({
    onSend,
    onStart,
    onFinish,
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
    listeners.current = { onSend, onStart, onFinish };
  }, [onSend, onStart, onFinish]);

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
  const { tasksRef, setTasks } = useSubtaskContext();
  const updateSubtask = useUpdateSubtask();

  const clearPreparedReplayMasks = useCallback(
    (replay: PendingPreparedReplayMask | null) => {
      if (!replay) {
        return;
      }
      setPendingSupersededRunIds((current) =>
        removeSetItems(current, [replay.targetRunId]),
      );
      setPendingSupersededMessageIds((current) =>
        removeSetItems(current, replay.supersededMessageIds),
      );
      if (pendingPreparedReplayRef.current === replay) {
        pendingPreparedReplayRef.current = null;
      }
    },
    [],
  );

  const thread = useStream<AgentThreadState>({
    client: getAPIClient(isMock),
    assistantId: "lead_agent",
    threadId: onStreamThreadId,
    reconnectOnMount: true,
    fetchStateHistory: { limit: 1 },
    // Batch stream updates received in the same macrotask without adding a
    // fixed debounce interval that could delay a continuously active stream.
    // Coalesce same-tick stream events into one React notification. Only the
    // boolean tier is safe: the SDK's numeric tier is a trailing debounce that
    // starves UI updates while chunks keep arriving faster than the window.
    // Keep explicit: SDK types claim @default true, but runtime uses throttle ?? false.
    throttle: true,
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
    onUpdateEvent(data, { mutate }) {
      if (hasRenderedThreadStateUpdate(data)) {
        mutate((previous) => reduceThreadStateUpdates(previous, data) ?? {});
      }

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
          renderedMessageSnapshotRef.current.threadId === threadIdRef.current
            ? renderedMessageSnapshotRef.current.messages
            : EMPTY_MESSAGES,
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
          const currentThreadId = threadIdRef.current;
          if (currentThreadId) {
            setThreadTitleInCaches(queryClient, currentThreadId, update.title);
          }
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

      if (eventType === "stream_replay_gap") {
        setOptimisticMessages([]);
        setOptimisticThreadId(null);
        setLiveMessagesThreadId(null);
        setPendingSupersededRunIds(new Set());
        setPendingSupersededMessageIds(new Set());
        messagesRef.current = [];
        transientHistoryBridgeRef.current = [];
        transientHistoryOrderRef.current = [];
        transientHistoryThreadIdRef.current = null;
        summarizedRef.current = new Set<string>();
        pendingUsageBaselineMessageIdsRef.current = new Set();
        localTurnOrderBaselineIdentitiesRef.current = null;
        tasksRef.current = {};
        setTasks({});
        invalidateStoppedThreadCaches(queryClient, threadIdRef.current, isMock);
        toast.warning(t.conversation.streamReplayGap);
        return;
      }

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
      pendingPreparedReplayRef.current = null;
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
      pendingPreparedReplayRef.current = null;
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
    const pendingReplay = pendingPreparedReplayRef.current;
    await stopThreadAndInvalidateCaches(
      queryClient,
      () => thread.stop(),
      stoppedThreadId,
      isMock,
    );
    if (pendingReplay) {
      setOptimisticMessages([]);
      setOptimisticThreadId(null);
      clearPreparedReplayMasks(pendingReplay);
    }
  }, [
    clearPreparedReplayMasks,
    displayThreadId,
    isMock,
    queryClient,
    thread,
    threadId,
  ]);

  const hasVisibleStreamState =
    Boolean(threadId) || liveMessagesThreadId === currentViewThreadId;
  const persistedMessages = useMemo(() => {
    if (!hasVisibleStreamState) {
      return EMPTY_MESSAGES;
    }
    const filtered = thread.messages.filter(
      (message) => !message.id || !pendingSupersededMessageIds.has(message.id),
    );
    // The SDK getter mints a fresh [] on every read while the stream has no
    // values; normalize to a stable identity so downstream effects keyed on
    // this array cannot re-fire (and setState-loop) on idle renders.
    return filtered.length === 0 ? EMPTY_MESSAGES : filtered;
  }, [hasVisibleStreamState, pendingSupersededMessageIds, thread.messages]);
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
  // Non-null only after a turn submitted by this mounted client. Keep it after
  // finish/stop/error because the SDK can retain its transient event order in
  // the settled frame. The next local submit replaces it and a thread switch or
  // replay gap clears it. An empty set is meaningful for a new thread and must
  // not be confused with a reconnect that has no local turn anchor.
  const localTurnOrderBaselineIdentitiesRef = useRef<Set<string> | null>(null);
  // Current-stream lifecycle bridge for messages removed from the checkpoint
  // tail before the canonical run-event page refetch observes the journal
  // flush. It is never appended into useThreadHistory's persisted pages.
  const transientHistoryBridgeRef = useRef<Message[]>([]);
  // Full identity order of each captured checkpoint. Confirmed bridge entries
  // are pruned from the message buffer, but remain here as non-rendering
  // anchors so an older rescue can be placed before a newest-first page.
  const transientHistoryOrderRef = useRef<readonly string[]>([]);
  const transientHistoryThreadIdRef = useRef<string | null>(null);
  // The run-scoped committed display ledger supplies message objects when a
  // compaction replacement outruns React or several rolling checkpoint windows
  // pass between compactions. The merged order separately anchors those
  // objects against canonical history.
  const renderedMessageSnapshotRef = useRef<{
    threadId: string | null;
    messages: Message[];
    order: readonly string[];
  }>({
    threadId: null,
    messages: EMPTY_MESSAGES,
    order: EMPTY_MESSAGE_IDENTITIES,
  });
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
    renderedMessageSnapshotRef.current = {
      threadId: null,
      messages: EMPTY_MESSAGES,
      order: EMPTY_MESSAGE_IDENTITIES,
    };
    summarizedRef.current = new Set<string>();
    pendingUsageBaselineMessageIdsRef.current = new Set();
    localTurnOrderBaselineIdentitiesRef.current = null;
    pendingPreparedReplayRef.current = null;
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
  // human message has arrived to avoid clearing before canonical history (or
  // replay-gap recovery) reports the input after individual messages-tuple
  // events for AI messages.
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

  useEffect(() => {
    if (
      optimisticMessageCount > 0 &&
      areOptimisticMessagesConfirmed(optimisticMessages, persistedMessages)
    ) {
      setOptimisticMessages([]);
      setOptimisticThreadId(null);
    }
  }, [optimisticMessageCount, optimisticMessages, persistedMessages]);

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
      localTurnOrderBaselineIdentitiesRef.current = new Set(
        pendingUsageBaselineMessageIdsRef.current,
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
            // No streamSubgraphs: subtask progress arrives via root-namespace
            // custom events, while subgraph frames would leak a delegated
            // subagent's values/messages into the thread view (#4399).
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
        localTurnOrderBaselineIdentitiesRef.current = null;
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

  const submitPreparedReplay = useCallback(
    async <TPrepared extends RegeneratePrepareResponse>({
      threadId,
      prepare,
      getSupersededMessageIds,
      getOptimisticMessages,
    }: {
      threadId: string;
      prepare: () => Promise<TPrepared>;
      getSupersededMessageIds: (prepared: TPrepared) => string[];
      getOptimisticMessages?: (prepared: TPrepared) => Message[];
    }) => {
      if (sendInFlightRef.current || !threadId) {
        return false;
      }
      sendInFlightRef.current = true;
      prevHumanMsgCountRef.current = humanMessageCount;
      pendingUsageBaselineMessageIdsRef.current = new Set(
        persistedMessages
          .map(messageIdentity)
          .filter((id): id is string => Boolean(id)),
      );
      localTurnOrderBaselineIdentitiesRef.current = new Set(
        pendingUsageBaselineMessageIdsRef.current,
      );
      setLiveMessagesThreadId(threadId);
      listeners.current.onSend?.(threadId);
      let preparedSupersededRunId: string | null = null;
      let preparedSupersededMessageIds: string[] = [];

      try {
        const prepared = await prepare();
        preparedSupersededRunId = prepared.target_run_id;
        preparedSupersededMessageIds = getSupersededMessageIds(prepared);
        prevHumanMsgCountRef.current = countHumanMessagesExcludingSuperseded(
          persistedMessages,
          preparedSupersededMessageIds,
        );
        const replacementHumanMessageId =
          "replacement_human_message_id" in prepared &&
          typeof prepared.replacement_human_message_id === "string"
            ? prepared.replacement_human_message_id
            : undefined;
        const pendingReplay: PendingPreparedReplayMask = {
          kind: replacementHumanMessageId ? "edit" : "regenerate",
          targetRunId: prepared.target_run_id,
          supersededMessageIds: preparedSupersededMessageIds,
          replacementHumanMessageId,
        };
        pendingPreparedReplayRef.current = pendingReplay;
        setPendingSupersededRunIds((current) => {
          const next = new Set(current);
          next.add(prepared.target_run_id);
          return next;
        });
        setPendingSupersededMessageIds((current) => {
          const next = new Set(current);
          for (const id of preparedSupersededMessageIds) {
            next.add(id);
          }
          return next;
        });

        const nextOptimisticMessages = getOptimisticMessages?.(prepared) ?? [];
        if (nextOptimisticMessages.length > 0) {
          setOptimisticThreadId(threadId);
          setOptimisticMessages(nextOptimisticMessages);
        }

        await thread.submit(prepared.input, {
          threadId,
          checkpoint: prepared.checkpoint,
          metadata: prepared.metadata,
          // No streamSubgraphs — same contract as the main submit path (#4399).
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
          queryKey: threadHistoryQueryKey(threadId),
        });
        void queryClient.invalidateQueries({
          queryKey: threadTokenUsageQueryKey(threadId),
        });
        return true;
      } catch (error) {
        setOptimisticMessages([]);
        setOptimisticThreadId(null);
        setLiveMessagesThreadId(null);
        localTurnOrderBaselineIdentitiesRef.current = null;
        if (preparedSupersededRunId) {
          const supersededRunId = preparedSupersededRunId;
          pendingPreparedReplayRef.current = null;
          setPendingSupersededRunIds((current) =>
            removeSetItems(current, [supersededRunId]),
          );
          setPendingSupersededMessageIds((current) =>
            removeSetItems(current, preparedSupersededMessageIds),
          );
        }
        toast.error(getStreamErrorMessage(error));
        return false;
      } finally {
        sendInFlightRef.current = false;
      }
    },
    [context, humanMessageCount, persistedMessages, queryClient, thread],
  );

  const regenerateMessage = useCallback(
    async (
      threadId: string,
      messageId: string,
      supersededMessageIds: string[] = [messageId],
    ) => {
      if (!messageId) {
        return false;
      }
      return submitPreparedReplay({
        threadId,
        prepare: async () => {
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
          return (await response.json()) as RegeneratePrepareResponse;
        },
        getSupersededMessageIds: () => supersededMessageIds,
      });
    },
    [submitPreparedReplay],
  );

  const editAndRegenerateMessage = useCallback(
    async (
      threadId: string,
      humanMessageId: string,
      replacementText: string,
    ) => {
      if (!humanMessageId) {
        return false;
      }
      return submitPreparedReplay<EditRegeneratePrepareResponse>({
        threadId,
        prepare: async () => {
          const response = await fetch(
            `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
              threadId,
            )}/runs/edit-regenerate/prepare`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              credentials: "include",
              body: JSON.stringify({
                human_message_id: humanMessageId,
                replacement_text: replacementText,
              }),
            },
          );
          if (!response.ok) {
            throw new Error(await readResponseErrorMessage(response));
          }
          return (await response.json()) as EditRegeneratePrepareResponse;
        },
        getSupersededMessageIds: (prepared) => prepared.source_message_ids,
        getOptimisticMessages: (prepared) => prepared.input.messages ?? [],
      });
    },
    [submitPreparedReplay],
  );

  // Cache the latest thread messages in a ref to compare against incoming history messages for deduplication,
  // and to allow access to the full message list in onUpdateEvent without causing re-renders.
  if (persistedMessages.length >= messagesRef.current.length) {
    messagesRef.current = persistedMessages;
  }

  // Render-facing coalesced snapshot. Refs, counters and usage tracking keep
  // consuming the per-chunk array above so lifecycle semantics (optimistic
  // clearing, summarization capture, token-usage baselines) are unchanged.
  const renderMessages = useCoalescedStreamMessages(
    persistedMessages,
    thread.isLoading,
  );

  const rawVisibleOptimisticMessages = getVisibleOptimisticMessages(
    optimisticThreadId === currentViewThreadId ? optimisticMessages : [],
    prevHumanMsgCountRef.current,
    humanMessageCount,
  );
  const visibleOptimisticMessages =
    rawVisibleOptimisticMessages.length === 0
      ? EMPTY_MESSAGES
      : rawVisibleOptimisticMessages;

  const transientHistoryOrder =
    transientHistoryBridgeRef.current.length > 0 &&
    transientHistoryThreadIdRef.current === threadId
      ? mergeTransientHistoryBridgeOrder(
          transientHistoryOrderRef.current,
          persistedMessages,
        )
      : transientHistoryOrderRef.current;
  const previouslyRenderedOrder =
    renderedMessageSnapshotRef.current.threadId === threadId
      ? renderedMessageSnapshotRef.current.order
      : EMPTY_MESSAGE_IDENTITIES;

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

  // The transient-bridge refs mutate in lockstep with stream/history updates
  // already captured by these deps, and resolveTransientHistoryBridge is
  // idempotent for entries canonical history has absorbed, so memoizing on the
  // coalesced snapshot cannot pin a stale bridge.
  const mergedMessages = useMemo(() => {
    const effectiveHistory = resolveThreadTransientHistoryBridge(
      visibleHistory,
      transientHistoryBridgeRef.current,
      transientHistoryThreadIdRef.current,
      threadId,
      transientHistoryOrder,
      previouslyRenderedOrder,
    );
    const merged = mergeMessages(
      effectiveHistory,
      renderMessages,
      visibleOptimisticMessages,
    );
    const localTurnOrderBaseline = localTurnOrderBaselineIdentitiesRef.current;
    return localTurnOrderBaseline === null
      ? restoreReconnectedTurnMessageOrder(merged)
      : restoreLocalTurnMessageOrder(merged, localTurnOrderBaseline);
  }, [
    previouslyRenderedOrder,
    renderMessages,
    threadId,
    transientHistoryOrder,
    visibleHistory,
    visibleOptimisticMessages,
  ]);
  useEffect(() => {
    const visibleMergedMessages = mergedMessages.filter(
      (message) =>
        !isHiddenFromUIMessage(message) && !message.id?.startsWith("opt-"),
    );
    const previousLedger =
      thread.isLoading &&
      renderedMessageSnapshotRef.current.threadId === threadId
        ? renderedMessageSnapshotRef.current.messages
        : EMPTY_MESSAGES;
    const renderedMessageLedger = mergeRenderedMessageLedger(
      previousLedger,
      visibleMergedMessages,
      pendingSupersededMessageIds,
    );
    renderedMessageSnapshotRef.current = {
      threadId: threadId ?? null,
      messages: renderedMessageLedger,
      order: renderedMessageLedger
        .map(messageIdentity)
        .filter(isNonEmptyString),
    };
  }, [mergedMessages, pendingSupersededMessageIds, thread.isLoading, threadId]);
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
    editAndRegenerateMessage,
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

export const THREAD_HISTORY_QUERY_POLICY = {
  refetchOnWindowFocus: false,
  staleTime: 5 * 60 * 1_000,
} as const;

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
    ...THREAD_HISTORY_QUERY_POLICY,
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
      return parseThreadMessagesPageResponse(await response.json());
    },
    getNextPageParam: getThreadHistoryNextPageParam,
  });

  const currentMessageRows = useMemo(
    () => flattenThreadHistoryPages(historyQuery.data?.pages ?? []),
    [historyQuery.data?.pages],
  );
  const [retainedHistory, setRetainedHistory] = useState<{
    threadId: string;
    rows: RunMessage[];
  }>({ threadId, rows: EMPTY_RUN_MESSAGES });
  const previousRows =
    retainedHistory.threadId === threadId
      ? retainedHistory.rows
      : EMPTY_RUN_MESSAGES;
  const pages = historyQuery.data?.pages ?? [];
  const isAuthoritativeComplete =
    historyQuery.isSuccess &&
    !historyQuery.isFetching &&
    pages.length > 0 &&
    pages.at(-1)?.has_more === false;
  const messageRows = useMemo(
    () =>
      reconcileThreadHistoryRows(
        previousRows,
        currentMessageRows,
        isAuthoritativeComplete,
      ),
    [currentMessageRows, isAuthoritativeComplete, previousRows],
  );

  useEffect(() => {
    setRetainedHistory((current) => {
      if (current.threadId === threadId && current.rows === messageRows) {
        return current;
      }
      return { threadId, rows: messageRows };
    });
  }, [messageRows, threadId]);

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

function mergeThreadMetadata(
  thread: AgentThread,
  metadata: ThreadMetadataPatch,
): AgentThread {
  return {
    ...thread,
    metadata: {
      ...(thread.metadata ?? {}),
      ...metadata,
    },
  };
}

function mergeThreadTitle(thread: AgentThread, title: string): AgentThread {
  return {
    ...thread,
    values: {
      ...thread.values,
      title,
    },
  };
}

function getThreadSnapshotCacheFilters(threadId: string) {
  return {
    search: {
      queryKey: ["threads", "search"],
      exact: false,
    },
    infiniteSearch: {
      queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      exact: false,
    },
    metadata: {
      queryKey: ["thread", "metadata", threadId],
      exact: false,
    },
  } as const;
}

function setThreadInCaches(
  queryClient: QueryClient,
  threadId: string,
  mapper: (thread: AgentThread) => AgentThread,
): void {
  const filters = getThreadSnapshotCacheFilters(threadId);

  queryClient.setQueriesData(
    filters.search,
    (oldData: Array<AgentThread> | undefined) => {
      if (!oldData) {
        return oldData;
      }
      return oldData.map((thread) =>
        thread.thread_id === threadId ? mapper(thread) : thread,
      );
    },
  );
  queryClient.setQueriesData(
    filters.infiniteSearch,
    (oldData: InfiniteData<AgentThread[]> | undefined) =>
      mapInfiniteThreadsCache(oldData, (thread) =>
        thread.thread_id === threadId ? mapper(thread) : thread,
      ),
  );
  queryClient.setQueriesData(
    filters.metadata,
    (oldData: AgentThread | null | undefined) =>
      oldData ? mapper(oldData) : oldData,
  );
}

function setThreadMetadataInCaches(
  queryClient: QueryClient,
  threadId: string,
  metadata: ThreadMetadataPatch,
) {
  setThreadInCaches(queryClient, threadId, (thread) =>
    mergeThreadMetadata(thread, metadata),
  );
}

export function setThreadTitleInCaches(
  queryClient: QueryClient,
  threadId: string,
  title: string,
): void {
  setThreadInCaches(queryClient, threadId, (thread) =>
    mergeThreadTitle(thread, title),
  );
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
    // Keep same-thread data visible during refetches without carrying usage
    // from the previous route into a newly selected thread.
    placeholderData: (previous) =>
      retainThreadTokenUsagePlaceholder(previous, threadId),
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

export function usePinThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      pinned,
    }: {
      threadId: string;
      pinned: boolean;
    }) =>
      patchThreadMetadata(threadId, {
        [THREAD_PINNED_METADATA_KEY]: pinned,
      }),
    onSuccess(response, { threadId, pinned }) {
      setThreadMetadataInCaches(queryClient, threadId, {
        ...(response.metadata ?? {}),
        [THREAD_PINNED_METADATA_KEY]: pinned,
      });
    },
    onSettled() {
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
    async onSuccess(_, { threadId, title }) {
      const filters: QueryFilters[] = Object.values(
        getThreadSnapshotCacheFilters(threadId),
      );

      // Prevent pre-rename snapshot requests from restoring the stale title.
      await Promise.all(
        filters.map((filter) => queryClient.cancelQueries(filter)),
      );
      setThreadTitleInCaches(queryClient, threadId, title);
      for (const filter of filters) {
        void queryClient.invalidateQueries(filter);
      }
    },
  });
}
