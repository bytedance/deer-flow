import type { Message } from "@langchain/langgraph-sdk";

import type { Translations } from "@/core/i18n/locales/types";
import {
  extractTextFromMessage,
  isHiddenFromUIMessage,
} from "@/core/messages/utils";
import {
  CHECK_FAILURE_CODES,
  goalReasonKeyOf,
  type GoalReasonKey,
} from "@/core/scheduled-tasks/goal-outcome";
import type { GoalState, ThreadGoalOutcome } from "@/core/threads/types";

/** The `goal_outcome` keys, in the order `contracts/thread_goal_contract.json` lists them. */
export const GOAL_OUTCOME_KEYS = [
  "status",
  "objective",
  "goal_created_at",
  "achieved_at",
  "continuation_count",
  "max_continuations",
  "reason",
  "relied_on_assumption",
  "reply_message_id",
] as const satisfies readonly (keyof ThreadGoalOutcome)[];

/**
 * English `last_evaluation.reason` values the host writes itself instead of
 * the evaluator (contract `host_reason_texts`). They are never shown as the
 * evaluator's note.
 */
export const GOAL_HOST_REASON_TEXTS: readonly string[] = [
  "No visible assistant evidence is available yet.",
  "The turn ended on a question to the user that has not been answered.",
  "No durable assistant end-of-turn receipt was available.",
];

export function isThreadGoalOutcome(
  value: unknown,
): value is ThreadGoalOutcome {
  // A primitive or an array has no `status`, so this rejects them too.
  const record = value as Record<string, unknown> | null;
  return (
    record?.status === "achieved" &&
    typeof record.objective === "string" &&
    typeof record.goal_created_at === "string"
  );
}

/** True when `outcome` records this very goal, not an earlier one with the same text. */
export function sameGoalInstance(
  goal: Pick<GoalState, "objective" | "created_at">,
  outcome: Pick<ThreadGoalOutcome, "objective" | "goal_created_at">,
): boolean {
  return (
    goal.objective === outcome.objective &&
    (goal.created_at ?? "") === outcome.goal_created_at
  );
}

/** Identity of one met record; a later record of the same goal text differs. */
export function goalOutcomeKey(outcome: ThreadGoalOutcome | null): string {
  if (!outcome) {
    return "none";
  }
  const { objective, goal_created_at, achieved_at } = outcome;
  return [objective, goal_created_at, achieved_at].join("|");
}

/**
 * Whether a message shows the conversation moved on: a visible human
 * message, or a visible AI message with text. The backend anchors the met
 * record on the latest visible AI message with text, so a tool-call-only or
 * empty AI message after that anchor is not a later turn either.
 */
function isVisibleConversationMessage(message: Message): boolean {
  return (
    !isHiddenFromUIMessage(message) &&
    (message.type === "human" ||
      (message.type === "ai" &&
        extractTextFromMessage(message).trim().length > 0))
  );
}

/**
 * "Goal met" stays current while its anchor reply is in the conversation and
 * nothing visible came after it. Derived from server state plus messages, so
 * a reload agrees with the live view.
 */
export function isGoalOutcomeCurrent(
  outcome: Pick<ThreadGoalOutcome, "reply_message_id">,
  messages: readonly Message[],
): boolean {
  const anchorId = outcome.reply_message_id;
  const anchorIndex = anchorId
    ? messages.findIndex((message) => message.id === anchorId)
    : -1;
  return (
    anchorIndex >= 0 &&
    !messages.slice(anchorIndex + 1).some(isVisibleConversationMessage)
  );
}

/** A row of the stand-down copy in `inputBox.goalBar.next`. */
export type GoalNextKey = keyof Translations["inputBox"]["goalBar"]["next"];
export type GoalStopKey = Exclude<GoalNextKey, "paused">;
/** Who acts next: amber "Stopped", primary "Waiting for you", muted otherwise. */
export type GoalBarChip = "stopped" | "waitingForYou" | "waiting" | "unchecked";

export type GoalBarView =
  | { kind: "none" }
  | { kind: "set"; goal: GoalState }
  | { kind: "inProgress"; goal: GoalState }
  | { kind: "continuing"; goal: GoalState; count: number; max: number }
  | {
      kind: "stopped";
      goal: GoalState;
      stop: GoalStopKey;
      chip: GoalBarChip;
      reasonKey: GoalReasonKey | null;
      count: number;
      max: number;
      /** The evaluator's own words; null when the host wrote the reason. */
      note: string | null;
      /** The stand-down code, only when this build has no copy for it. */
      rawCode: string | null;
    }
  | { kind: "paused"; goal: GoalState; count: number; max: number }
  | {
      kind: "met";
      outcome: ThreadGoalOutcome;
      count: number;
      max: number;
      reliedOnAssumption: boolean;
      note: string | null;
    };

function countOf(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : 0;
}

function evaluatorNote(reason: unknown): string | null {
  const note = typeof reason === "string" ? reason.trim() : "";
  return note && !GOAL_HOST_REASON_TEXTS.includes(note) ? note : null;
}

type StopRow = { stop: GoalStopKey; chip: GoalBarChip };

// Stand-down codes that map one-to-one through the shared reason keys.
const STOP_BY_REASON: Partial<Record<GoalReasonKey, StopRow>> = {
  noProgress: { stop: "noProgress", chip: "stopped" },
  tokenCapped: { stop: "tokenCapped", chip: "stopped" },
  missingEvidence: { stop: "missingEvidence", chip: "stopped" },
  runFailed: { stop: "runFailed", chip: "stopped" },
  externalWait: { stop: "external", chip: "waiting" },
};

function stopRowOf(
  code: string,
  max: number,
  hasOpenHumanInputCard: boolean,
): StopRow {
  if (CHECK_FAILURE_CODES.includes(code)) {
    return { stop: "unchecked", chip: "unchecked" };
  }
  const reasonKey = goalReasonKeyOf(code);
  if (reasonKey === "maxContinuations") {
    return { stop: max > 0 ? "limit" : "autoOff", chip: "stopped" };
  }
  if (reasonKey === "needsUserInput") {
    // Either the turn ended on an open question card, or the evaluator saw
    // the agent guess; only the first has a question to answer.
    const stop = hasOpenHumanInputCard ? "needsInputCard" : "needsInputReply";
    return { stop, chip: "waitingForYou" };
  }
  const row = reasonKey ? STOP_BY_REASON[reasonKey] : undefined;
  return row ?? { stop: "unknown", chip: "stopped" };
}

/**
 * The goal bar state. An active goal always wins over a met record; while a
 * run streams, a stand-down reason left by an earlier run is not shown.
 * Idle: a stand-down, then a paused auto-continue, then a plain set goal.
 * `outcome` is a record `useActiveGoal` already judged current.
 */
export function describeGoalBar({
  goal,
  outcome,
  isRunning,
  hasOpenHumanInputCard = false,
}: {
  goal: GoalState | null;
  outcome: ThreadGoalOutcome | null;
  isRunning: boolean;
  hasOpenHumanInputCard?: boolean;
}): GoalBarView {
  if (goal) {
    const evaluation = goal.last_evaluation;
    const code = evaluation?.stand_down_reason?.trim() ?? "";
    const count = countOf(goal.continuation_count);
    const max = countOf(goal.max_continuations);
    if (isRunning) {
      return !code && evaluation?.satisfied !== true && count > 0
        ? { kind: "continuing", goal, count, max }
        : { kind: "inProgress", goal };
    }
    if (code) {
      const row = stopRowOf(code, max, hasOpenHumanInputCard);
      return {
        kind: "stopped",
        goal,
        ...row,
        reasonKey: goalReasonKeyOf(code),
        count,
        max,
        // A failed check has no verdict to show, even when the stored
        // evaluation says satisfied.
        note:
          row.stop === "unchecked" ? null : evaluatorNote(evaluation?.reason),
        rawCode: row.stop === "unknown" ? code : null,
      };
    }
    if (evaluation && count > 0) {
      // No checker note: when a satisfied verdict's clear was skipped, the
      // stored evaluation is the earlier unmet one.
      return { kind: "paused", goal, count, max };
    }
    return { kind: "set", goal };
  }
  if (outcome) {
    return {
      kind: "met",
      outcome,
      count: countOf(outcome.continuation_count),
      max: countOf(outcome.max_continuations),
      reliedOnAssumption: outcome.relied_on_assumption === true,
      note: evaluatorNote(outcome.reason),
    };
  }
  return { kind: "none" };
}

function fill(template: string, values: Record<string, string | number>) {
  // Function replacer, so an objective with `$&`/`$1` stays literal.
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
}

export type GoalBarCopy = {
  /** "Goal" or "Goal met". */
  label: string;
  objective: string;
  /** The state chip; null for a plain set goal and a met goal. */
  chip: string | null;
  /** A met goal's auto-continue count; null when it never auto-continued. */
  meta: string | null;
  /** The second line: why it stopped and what to do next. */
  detail: string | null;
  /** Live-region text; empty for states that are not announced. */
  announcement: string;
};

/** Localized copy of a goal bar state; null when no bar is shown. */
export function describeGoalBarCopy(
  view: GoalBarView,
  t: Translations,
): GoalBarCopy | null {
  const bar = t.inputBox.goalBar;
  const announce = (status: string, detail: string) =>
    fill(bar.announce, { status, detail });
  if (view.kind === "none") {
    return null;
  }
  if (view.kind === "met") {
    const { count } = view;
    return {
      label: t.scheduledTasks.goal.met,
      objective: view.outcome.objective,
      chip: null,
      meta:
        count === 1
          ? bar.autoContinuedOnce
          : count > 1
            ? fill(bar.autoContinuedMany, { count })
            : null,
      detail: null,
      announcement: announce(t.scheduledTasks.goal.met, view.outcome.objective),
    };
  }
  const copy: GoalBarCopy = {
    label: t.inputBox.goalLabel,
    objective: view.goal.objective,
    chip: null,
    meta: null,
    detail: null,
    announcement: "",
  };
  // Stopped and paused rows announce their chip with the next step.
  const withDetail = (chip: string, detail: string) => ({
    ...copy,
    chip,
    detail,
    announcement: announce(chip, detail),
  });
  switch (view.kind) {
    case "set":
      return copy;
    case "inProgress":
      return { ...copy, chip: bar.inProgress };
    case "continuing": {
      const chip = fill(t.inputBox.goalContinuing, {
        count: view.count,
        max: view.max,
      });
      return { ...copy, chip, announcement: announce(copy.label, chip) };
    }
    case "paused":
      return withDetail(
        bar.paused,
        fill(bar.next.paused, { count: view.count, max: view.max }),
      );
    case "stopped": {
      const goalCopy = t.scheduledTasks.goal;
      // Only the "unchecked" row names its reason, in the scheduled page's
      // words after the "Couldn't check the goal" its chip already shows.
      const uncheckedReasons: Partial<Record<GoalReasonKey, string>> =
        bar.uncheckedReasons;
      const reason = view.reasonKey
        ? (uncheckedReasons[view.reasonKey] ?? goalCopy.reasons[view.reasonKey])
        : goalCopy.unchecked;
      return withDetail(
        view.chip === "unchecked" ? goalCopy.unchecked : bar[view.chip],
        fill(bar.next[view.stop], { count: view.count, max: view.max, reason }),
      );
    }
  }
}

/**
 * What the live region and Details key on: a new state, or the same state of
 * another goal (a thread switch), changes it. Streaming re-renders and a
 * rising counter do not, and a set or in-progress goal is silent.
 */
export function goalBarAnnounceKey(view: GoalBarView): string {
  if (
    view.kind === "none" ||
    view.kind === "set" ||
    view.kind === "inProgress"
  ) {
    return "";
  }
  if (view.kind === "met") {
    return `met:${goalOutcomeKey(view.outcome)}`;
  }
  const state = view.kind === "stopped" ? `stopped:${view.stop}` : view.kind;
  return [state, view.goal.objective, view.goal.created_at].join("|");
}

/**
 * Stable signature of the *server* goal, used to decide when an optimistic
 * client override should yield back to server state.
 *
 * It changes whenever a new goal is set (`created_at`), the agent auto-continues
 * (`continuation_count`/`updated_at`), or the backend clears/satisfies the goal
 * (`null`). `useActiveGoal` resets its optimistic copy when this key changes, so
 * the streamed continuation counter is never permanently shadowed.
 */
export function goalReconciliationKey(goal: GoalState | null): string {
  if (!goal) {
    return "none";
  }
  return [
    goal.objective,
    goal.status,
    goal.created_at ?? "",
    goal.updated_at ?? "",
    goal.continuation_count ?? 0,
  ].join("|");
}
