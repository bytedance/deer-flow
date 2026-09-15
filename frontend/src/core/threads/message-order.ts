/**
 * Trusted ordering for the merged chat message view.
 *
 * A normalized identity carries two independent facts, tracked separately:
 *
 * - latest visible content: live copies refresh history copies, but a hidden
 *   checkpoint control message never overwrites a visible user turn;
 * - trusted position: a valid `deerflow_seq` stamped by the current thread's
 *   REST feed or by server-stamped state/live frames. Only positive safe
 *   integers qualify; a missing or invalid value never overwrites a known
 *   one, and several trusted values for one identity converge to the
 *   earliest feed position (mirroring the backend `get_message_seqs`
 *   earliest-seq-wins rule).
 *
 * Ordering uses a skeleton of every identity with a trusted seq, sorted by
 * position, and weaves segments without seq around shared-identity anchors
 * exactly as before: internal segment order is preserved, a segment goes
 * before its next anchor. Live-only positioned entries within the loaded
 * window also anchor trailing segments; rescued prefixes before that window
 * leave new steps at the tail. Conflicting speculative constraints lose to
 * the skeleton. `deerflow_seq` is server-owned display metadata — it is
 * never written back into a checkpoint by the client.
 *
 * This module is pure: no React, no caches, no per-thread state. Callers
 * scope inputs to the current thread, so switching threads, branching, or
 * replaying cannot inherit positions.
 */
import type { Message } from "@langchain/langgraph-sdk";

import { getMessageRunId } from "../messages/run-duration";
import { isHiddenFromUIMessage } from "../messages/utils";

// Thread-global feed position, attached by the backend to history rows and to
// `values` frame messages it has already persisted. Mirrors MESSAGE_SEQ_KEY in
// `deerflow/runtime/events/message_identity.py`.
export const MESSAGE_SEQ_KEY = "deerflow_seq";

const INJECTED_USER_MESSAGE_ID_SUFFIX = "__user";

export function messageIdentity(message: Message): string | undefined {
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

/** A seq is trustworthy only as a positive safe integer. */
export function isValidMessageSeq(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

/** Thread-global feed position, when the message carries a trustworthy one. */
export function trustedMessageSeq(message: Message): number | undefined {
  const seq = message.additional_kwargs?.[MESSAGE_SEQ_KEY];
  return isValidMessageSeq(seq) ? seq : undefined;
}

export function dedupeMessagesByIdentity(messages: Message[]): Message[] {
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

/**
 * Insert messages carrying a trusted seq into an already-ordered list at
 * their position. Entries without a trustworthy position are never moved to
 * accommodate an insertion, and an *inserted* message whose seq exceeds every
 * known position keeps the established tail. Shared by mergeMessages'
 * callers that overlay rescued messages onto canonical history, so the seq
 * skeleton always outranks anchor guesses.
 */
export function insertByTrustedSeq(
  base: Message[],
  positioned: Message[],
): Message[] {
  if (positioned.length === 0) {
    return base;
  }
  const sorted = [...positioned].sort(
    (left, right) =>
      (trustedMessageSeq(left) ?? Number.POSITIVE_INFINITY) -
      (trustedMessageSeq(right) ?? Number.POSITIVE_INFINITY),
  );
  const result: Message[] = [];
  let next = 0;
  for (const message of base) {
    const seq = trustedMessageSeq(message);
    if (seq !== undefined) {
      while (
        next < sorted.length &&
        (trustedMessageSeq(sorted[next]!) ?? Number.POSITIVE_INFINITY) < seq
      ) {
        result.push(sorted[next]!);
        next += 1;
      }
    }
    result.push(message);
  }
  while (next < sorted.length) {
    result.push(sorted[next]!);
    next += 1;
  }
  return result;
}

type PositionedMessage = {
  message: Message;
  // Tuple sort key. Seq-positioned entries sit at [seq, 0]; everything else
  // anchors to a positioned neighbour (see mergeMessages). Equal keys fall
  // back to insertion order via the stable sort, which keeps a no-seq
  // segment's internal order without extra key spacing.
  major: number;
  minor: number;
};

/**
 * Merge canonical history, the live checkpoint tail, and optimistic messages
 * into one display list.
 *
 * Steps (design §4.2):
 * 1. Content and position are merged per identity: the freshest visible copy
 *    supplies content, the earliest valid seq supplies the trusted position.
 * 2. Every identity with a trusted seq joins an ascending skeleton — covering
 *    rows before the loaded window, gaps inside it, rows after it, and the
 *    no-shared-identity case alike (this replaces the old canonicalMinSeq
 *    local rule, which could not place a window-internal gap: R4).
 * 3. Live-only messages without a seq keep the existing anchor weaving: a
 *    pending segment goes before its next shared or positioned anchor. A
 *    trailing segment follows its last live-only positioned anchor unless
 *    that anchor predates the loaded window; otherwise it keeps the tail.
 *    Its internal order is untouched.
 * 4. When a speculative anchor and the skeleton disagree, the skeleton wins;
 *    established seq order is never reversed to fit a no-seq segment.
 *
 * Content replacement keeps trusted ordering metadata (R3): a live copy
 * without a seq refreshes the text but inherits the known position, run_id,
 * and turn_duration instead of resetting them.
 *
 * Runs in O(n log n) per structural change: identity lookups are Map/Set and
 * the single sort happens once per merged snapshot, not per token.
 */
export function mergeMessages(
  historyMessages: Message[],
  threadMessages: Message[],
  optimisticMessages: Message[],
): Message[] {
  // Pass 1: per-identity trusted position and the historical metadata worth
  // preserving. The earliest valid seq across copies wins; a hidden control
  // copy only contributes a position when no visible copy carries one, so a
  // re-keyed reminder can never drag the visible user turn to its own row.
  const visibleSeqByIdentity = new Map<string, number>();
  const anySeqByIdentity = new Map<string, number>();
  const savedTurnDurations = new Map<string, number>();
  const savedRunIds = new Map<string, string>();
  const collectTrustedSeq = (message: Message) => {
    const identity = messageIdentity(message);
    if (!identity) {
      return;
    }
    const seq = trustedMessageSeq(message);
    if (seq === undefined) {
      return;
    }
    const known = anySeqByIdentity.get(identity);
    if (known === undefined || seq < known) {
      anySeqByIdentity.set(identity, seq);
    }
    if (!isHiddenFromUIMessage(message)) {
      const knownVisible = visibleSeqByIdentity.get(identity);
      if (knownVisible === undefined || seq < knownVisible) {
        visibleSeqByIdentity.set(identity, seq);
      }
    }
  };
  const trustedSeqOf = (identity: string | undefined) =>
    identity === undefined
      ? undefined
      : (visibleSeqByIdentity.get(identity) ?? anySeqByIdentity.get(identity));
  for (const message of historyMessages) {
    collectTrustedSeq(message);
    const identity = messageIdentity(message);
    const runId = getMessageRunId(message);
    if (identity && runId) {
      savedRunIds.set(identity, runId);
    }
    if (identity && message.additional_kwargs?.turn_duration !== undefined) {
      savedTurnDurations.set(
        identity,
        message.additional_kwargs.turn_duration as number,
      );
    }
  }
  for (const message of threadMessages) {
    collectTrustedSeq(message);
  }

  const canonical = dedupeMessagesByIdentity(historyMessages);
  const live = dedupeMessagesByIdentity(threadMessages);
  const canonicalByIdentity = new Map(
    canonical.flatMap((message) => {
      const identity = messageIdentity(message);
      return identity ? [[identity, message] as const] : [];
    }),
  );

  // Pass 2: walk the live tail. Shared identities are ordering anchors and
  // may replace the canonical content; live-only messages with a trusted seq
  // join the skeleton; the rest accumulate into no-seq segments woven before
  // their next shared anchor.
  const replacementByIdentity = new Map<string, Message>();
  const beforeAnchor = new Map<string, Message[]>();
  const skeletonLive: Message[] = [];
  let pending: Message[] = [];
  let trailingAnchorSeq: number | undefined;
  for (const message of live) {
    const identity = messageIdentity(message);
    const canonicalMessage = identity
      ? canonicalByIdentity.get(identity)
      : undefined;
    if (identity && canonicalMessage) {
      if (pending.length > 0) {
        beforeAnchor.set(identity, [
          ...(beforeAnchor.get(identity) ?? []),
          ...pending,
        ]);
      }
      pending = [];
      trailingAnchorSeq = undefined;
      // A hidden checkpoint control message must not replace a visible
      // canonical user turn that happens to reuse its identity. In every
      // other case the live checkpoint copy is fresher and replaces history
      // without moving it.
      if (
        !isHiddenFromUIMessage(message) ||
        isHiddenFromUIMessage(canonicalMessage)
      ) {
        replacementByIdentity.set(identity, message);
      }
      continue;
    }
    if (identity && trustedSeqOf(identity) !== undefined) {
      // A positioned live-only result also anchors its preceding steps.
      beforeAnchor.set(identity, pending);
      pending = [];
      skeletonLive.push(message);
      trailingAnchorSeq = trustedSeqOf(identity);
      continue;
    }
    pending.push(message);
  }
  // Only a live-only positioned anchor can pull trailing steps into a gap.
  // After a shared anchor, preserve canonical source order before the tail.
  const trailingPending = pending;

  // Pass 3: position canonical entries. A canonical entry without a trusted
  // seq stays in its established position relative to the previous
  // seq-positioned entry (or at the front when none exists yet).
  const entries: PositionedMessage[] = [];
  let minorCounter = 0;
  let previousCanonicalSeq = 0;
  let firstCanonicalSeq = Number.POSITIVE_INFINITY;
  for (const message of canonical) {
    const identity = messageIdentity(message);
    const seq = trustedSeqOf(identity);
    let major: number;
    let minor: number;
    if (seq !== undefined) {
      major = seq;
      minor = 0;
      previousCanonicalSeq = seq;
      firstCanonicalSeq = Math.min(firstCanonicalSeq, seq);
    } else {
      major = previousCanonicalSeq;
      minor = ++minorCounter;
    }
    if (identity) {
      // A no-seq segment known to precede this anchor sorts immediately
      // before it; stable sort keeps the segment's internal order.
      const segment = beforeAnchor.get(identity);
      if (segment) {
        for (const segmentMessage of segment) {
          entries.push({
            message: segmentMessage,
            major,
            minor: minor - 0.5,
          });
        }
      }
    }
    const replacement = identity
      ? replacementByIdentity.get(identity)
      : undefined;
    entries.push({ message: replacement ?? message, major, minor });
  }
  for (const message of skeletonLive) {
    const seq = trustedSeqOf(messageIdentity(message));
    if (seq !== undefined) {
      for (const segmentMessage of beforeAnchor.get(
        messageIdentity(message)!,
      ) ?? []) {
        entries.push({ message: segmentMessage, major: seq, minor: -0.5 });
      }
      entries.push({ message, major: seq, minor: 0 });
    }
  }
  // A rescued early input may precede an unloaded history gap while its
  // followers belong to the new run (#4666). Keep those followers at the
  // tail; within the loaded window, keep trailing steps beside their result.
  const trailingMajor =
    trailingAnchorSeq !== undefined && trailingAnchorSeq >= firstCanonicalSeq
      ? trailingAnchorSeq
      : Number.POSITIVE_INFINITY;
  for (const message of trailingPending) {
    entries.push({ message, major: trailingMajor, minor: 0.5 });
  }
  for (const message of optimisticMessages) {
    entries.push({
      message,
      major: Number.POSITIVE_INFINITY,
      minor: ++minorCounter,
    });
  }

  const ordered = entries
    .slice()
    .sort((left, right) => left.major - right.major || left.minor - right.minor)
    .map((entry) => entry.message);

  const merged = dedupeMessagesByIdentity(ordered);

  // Pass 4: re-attach trusted ordering metadata that content replacement
  // dropped. A missing or invalid seq never overwrites the known position;
  // other additional_kwargs, run_id, and turn_duration of the winning content
  // copy ride along untouched.
  return merged.map((message) => {
    const identity = messageIdentity(message);
    if (!identity) {
      return message;
    }
    const trustedSeq = trustedSeqOf(identity);
    const shouldRestoreSeq =
      trustedSeq !== undefined && trustedMessageSeq(message) !== trustedSeq;
    const shouldRestoreRunId =
      savedRunIds.has(identity) && !getMessageRunId(message);
    const shouldRestoreTurnDuration =
      savedTurnDurations.has(identity) &&
      message.additional_kwargs?.turn_duration === undefined;
    if (
      !shouldRestoreSeq &&
      !shouldRestoreRunId &&
      !shouldRestoreTurnDuration
    ) {
      return message;
    }
    return {
      ...message,
      ...(shouldRestoreRunId ? { run_id: savedRunIds.get(identity) } : {}),
      additional_kwargs: {
        ...message.additional_kwargs,
        ...(shouldRestoreSeq ? { [MESSAGE_SEQ_KEY]: trustedSeq } : {}),
        ...(shouldRestoreTurnDuration
          ? { turn_duration: savedTurnDurations.get(identity) }
          : {}),
      },
    } as Message;
  });
}
