import type { Message } from "@langchain/langgraph-sdk";

import type { Translations } from "@/core/i18n/locales/types";

import { getUsageMetadata, type TokenUsage } from "./usage";
import { hasContent } from "./utils";

export type TokenUsageInlineMode = "off" | "per_turn" | "step_debug";

export interface TokenUsagePreferences {
  headerTotal: boolean;
  inlineMode: TokenUsageInlineMode;
}

export type TokenUsageViewPreset = "off" | "summary" | "per_turn" | "debug";

export interface TokenDebugStep {
  id: string;
  messageId: string;
  label: string;
  secondaryLabels: string[];
  usage: TokenUsage | null;
  sharedAttribution: boolean;
}

type TokenUsageAttributionAction =
  | {
      kind: "todo_start" | "todo_complete" | "todo_update" | "todo_remove";
      content?: string;
      tool_call_id?: string;
    }
  | {
      kind: "subagent";
      description?: string | null;
      subagent_type?: string | null;
      tool_call_id?: string;
    }
  | {
      kind: "search";
      query?: string | null;
      tool_name?: string | null;
      tool_call_id?: string;
    }
  | {
      kind: "present_files" | "clarification";
      tool_call_id?: string;
    }
  | {
      kind: "tool";
      tool_name?: string | null;
      description?: string | null;
      tool_call_id?: string;
    };

interface TokenUsageAttribution {
  version?: number;
  kind?:
    | "thinking"
    | "final_answer"
    | "tool_batch"
    | "todo_update"
    | "subagent_dispatch";
  shared_attribution?: boolean;
  tool_call_ids?: string[];
  actions?: TokenUsageAttributionAction[];
}

// Precise write_todos labels come from the backend attribution payload.
// The frontend fallback intentionally stays generic so we do not duplicate
// backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py
//::_build_todo_actions and risk the two diffing algorithms drifting apart.

export function getTokenUsageViewPreset(
  preferences: TokenUsagePreferences,
): TokenUsageViewPreset {
  if (!preferences.headerTotal && preferences.inlineMode === "off") {
    return "off";
  }
  if (preferences.headerTotal && preferences.inlineMode === "off") {
    return "summary";
  }
  if (preferences.inlineMode === "step_debug") {
    return "debug";
  }
  return "per_turn";
}

export function tokenUsagePreferencesFromPreset(
  preset: TokenUsageViewPreset,
): TokenUsagePreferences {
  switch (preset) {
    case "off":
      return { headerTotal: false, inlineMode: "off" };
    case "summary":
      return { headerTotal: true, inlineMode: "off" };
    case "debug":
      return { headerTotal: true, inlineMode: "step_debug" };
    case "per_turn":
    default:
      return { headerTotal: true, inlineMode: "per_turn" };
  }
}

export function buildTokenDebugSteps(
  messages: Message[],
  t: Translations,
): TokenDebugStep[] {
  const steps: TokenDebugStep[] = [];

  for (const [index, message] of messages.entries()) {
    if (message.type !== "ai") {
      continue;
    }

    const usage = getUsageMetadata(message);
    const attribution = getTokenUsageAttribution(message);
    const actionLabels: string[] = [];

    if (attribution) {
      actionLabels.push(...buildActionLabelsFromAttribution(attribution, t));

      if (actionLabels.length === 0) {
        if (attribution.kind === "final_answer") {
          actionLabels.push(t.tokenUsage.finalAnswer);
        } else if (attribution.kind === "thinking") {
          actionLabels.push(t.common.thinking);
        }
      }

      if (actionLabels.length > 0) {
        const sharedAttribution =
          attribution.shared_attribution ?? actionLabels.length > 1;
        steps.push({
          id: message.id ?? `token-step-${index}`,
          messageId: message.id ?? `token-step-${index}`,
          label:
            sharedAttribution && actionLabels.length > 1
              ? t.tokenUsage.stepTotal
              : actionLabels[0]!,
          secondaryLabels:
            sharedAttribution && actionLabels.length > 1 ? actionLabels : [],
          usage,
          sharedAttribution,
        });
        continue;
      }
    }

    for (const toolCall of message.tool_calls ?? []) {
      const toolArgs = (toolCall.args ?? {}) as Record<string, unknown>;

      if (toolCall.name === "write_todos") {
        actionLabels.push(t.toolCalls.writeTodos);
        continue;
      }

      actionLabels.push(
        describeToolCall(
          {
            name: toolCall.name,
            args: toolArgs,
          },
          t,
        ),
      );
    }

    if (actionLabels.length === 0) {
      if (hasContent(message)) {
        actionLabels.push(t.tokenUsage.finalAnswer);
      } else {
        actionLabels.push(t.common.thinking);
      }
    }

    steps.push({
      id: message.id ?? `token-step-${index}`,
      messageId: message.id ?? `token-step-${index}`,
      label:
        actionLabels.length === 1 ? actionLabels[0]! : t.tokenUsage.stepTotal,
      secondaryLabels: actionLabels.length > 1 ? actionLabels : [],
      usage,
      sharedAttribution: actionLabels.length > 1,
    });
  }

  return steps;
}

function getTokenUsageAttribution(
  message: Message,
): TokenUsageAttribution | null {
  if (message.type !== "ai") {
    return null;
  }

  const additionalKwargs = message.additional_kwargs;
  if (!additionalKwargs || typeof additionalKwargs !== "object") {
    return null;
  }

  const attribution = (additionalKwargs as Record<string, unknown>)
    .token_usage_attribution;
  const normalized = normalizeTokenUsageAttribution(attribution);
  if (!normalized) {
    return null;
  }

  return normalized;
}

function buildActionLabelsFromAttribution(
  attribution: TokenUsageAttribution,
  t: Translations,
): string[] {
  return (attribution.actions ?? [])
    .map((action) => describeAttributionAction(action, t))
    .filter((label): label is string => !!label);
}

function describeAttributionAction(
  action: TokenUsageAttributionAction,
  t: Translations,
): string | null {
  switch (action.kind) {
    case "todo_start":
      return action.content
        ? t.tokenUsage.startTodo(action.content)
        : t.toolCalls.writeTodos;
    case "todo_complete":
      return action.content
        ? t.tokenUsage.completeTodo(action.content)
        : t.toolCalls.writeTodos;
    case "todo_update":
      return action.content
        ? t.tokenUsage.updateTodo(action.content)
        : t.toolCalls.writeTodos;
    case "todo_remove":
      return action.content
        ? t.tokenUsage.removeTodo(action.content)
        : t.toolCalls.writeTodos;
    case "subagent":
      return t.tokenUsage.subagent(action.description ?? t.subtasks.subtask);
    case "search":
      if (action.query) {
        return t.toolCalls.searchFor(action.query);
      }
      return t.toolCalls.useTool(action.tool_name ?? "search");
    case "present_files":
      return t.toolCalls.presentFiles;
    case "clarification":
      return t.toolCalls.needYourHelp;
    case "tool":
      return describeToolCall(
        {
          name: action.tool_name ?? "tool",
          args: action.description ? { description: action.description } : {},
        },
        t,
      );
    default:
      return null;
  }
}

function describeToolCall(
  toolCall: {
    name: string;
    args: Record<string, unknown>;
  },
  t: Translations,
): string {
  if (toolCall.name === "task") {
    const description =
      typeof toolCall.args.description === "string"
        ? toolCall.args.description
        : t.subtasks.subtask;
    return t.tokenUsage.subagent(description);
  }

  if (
    (toolCall.name === "web_search" || toolCall.name === "image_search") &&
    typeof toolCall.args.query === "string"
  ) {
    return t.toolCalls.searchFor(toolCall.args.query);
  }

  if (toolCall.name === "web_fetch") {
    return t.toolCalls.viewWebPage;
  }

  if (toolCall.name === "present_files") {
    return t.toolCalls.presentFiles;
  }

  if (toolCall.name === "ask_clarification") {
    return t.toolCalls.needYourHelp;
  }

  if (typeof toolCall.args.description === "string") {
    return toolCall.args.description;
  }

  return t.toolCalls.useTool(toolCall.name);
}

function normalizeTokenUsageAttribution(
  value: unknown,
): TokenUsageAttribution | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const rawActions = record.actions;
  if (rawActions !== undefined && !Array.isArray(rawActions)) {
    return null;
  }

  return {
    // Versioning is additive for now: the frontend should ignore unknown
    // fields and fall back when required fields become incompatible.
    version: typeof record.version === "number" ? record.version : undefined,
    kind: isTokenUsageAttributionKind(record.kind) ? record.kind : undefined,
    shared_attribution:
      typeof record.shared_attribution === "boolean"
        ? record.shared_attribution
        : undefined,
    tool_call_ids: Array.isArray(record.tool_call_ids)
      ? record.tool_call_ids.filter(
          (toolCallId): toolCallId is string =>
            typeof toolCallId === "string" && toolCallId.trim().length > 0,
        )
      : undefined,
    actions: Array.isArray(rawActions)
      ? rawActions
          .map((action) => normalizeTokenUsageAttributionAction(action))
          .filter(
            (action): action is TokenUsageAttributionAction => action !== null,
          )
      : undefined,
  };
}

function normalizeTokenUsageAttributionAction(
  value: unknown,
): TokenUsageAttributionAction | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const kind = record.kind;
  if (
    kind !== "todo_start" &&
    kind !== "todo_complete" &&
    kind !== "todo_update" &&
    kind !== "todo_remove" &&
    kind !== "subagent" &&
    kind !== "search" &&
    kind !== "present_files" &&
    kind !== "clarification" &&
    kind !== "tool"
  ) {
    return null;
  }

  const content = readString(record.content);
  const toolCallId = readString(record.tool_call_id);

  switch (kind) {
    case "todo_start":
    case "todo_complete":
    case "todo_update":
    case "todo_remove":
      return {
        kind,
        content,
        tool_call_id: toolCallId,
      };
    case "subagent":
      return {
        kind,
        description: readString(record.description),
        subagent_type: readString(record.subagent_type),
        tool_call_id: toolCallId,
      };
    case "search":
      return {
        kind,
        query: readString(record.query),
        tool_name: readString(record.tool_name),
        tool_call_id: toolCallId,
      };
    case "present_files":
    case "clarification":
      return {
        kind,
        tool_call_id: toolCallId,
      };
    case "tool":
      return {
        kind,
        tool_name: readString(record.tool_name),
        description: readString(record.description),
        tool_call_id: toolCallId,
      };
    default:
      return null;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  return value as Record<string, unknown>;
}

function readString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

function isTokenUsageAttributionKind(
  value: unknown,
): value is NonNullable<TokenUsageAttribution["kind"]> {
  return (
    value === "thinking" ||
    value === "final_answer" ||
    value === "tool_batch" ||
    value === "todo_update" ||
    value === "subagent_dispatch"
  );
}
