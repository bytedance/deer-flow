import type { Message } from "@langchain/langgraph-sdk";

import { extractTextFromMessage } from "../messages/utils";

import { normalizeThreadHistoryFileKey } from "./utils";

type FileHistoryOperation = "write_file" | "str_replace";

interface WriteFileToolArgs {
  description?: string;
  path?: string;
  content?: string;
}

interface StrReplaceToolArgs {
  description?: string;
  path?: string;
  old_str?: string;
  new_str?: string;
  replace_all?: boolean;
}

export interface ThreadFileHistorySnapshot {
  id: string;
  filepath: string;
  normalizedPath: string;
  version: number;
  sequence: number;
  operation: FileHistoryOperation;
  description?: string;
  content: string;
  previousContent?: string;
  messageId?: string;
  toolCallId?: string;
}

export type ThreadFileHistory = Record<string, ThreadFileHistorySnapshot[]>;

function isSuccessfulToolCallResult(result: string | undefined) {
  return result !== undefined && !result.startsWith("Error:");
}

function buildToolResultMap(messages: Message[]) {
  const resultMap = new Map<string, string>();

  for (const message of messages) {
    if (message.type !== "tool" || !message.tool_call_id) {
      continue;
    }

    resultMap.set(message.tool_call_id, extractTextFromMessage(message));
  }

  return resultMap;
}

function applyStringReplacement({
  content,
  oldStr,
  newStr,
  replaceAll,
}: {
  content: string;
  oldStr: string;
  newStr: string;
  replaceAll: boolean;
}) {
  if (!content.includes(oldStr)) {
    return null;
  }

  if (replaceAll) {
    return content.split(oldStr).join(newStr);
  }

  return content.replace(oldStr, newStr);
}

export function buildThreadFileHistory(messages: Message[]): ThreadFileHistory {
  const history: ThreadFileHistory = {};
  const latestContentByPath = new Map<string, string>();
  const toolResults = buildToolResultMap(messages);
  let sequence = 0;

  for (const message of messages) {
    if (message.type !== "ai") {
      continue;
    }

    for (const toolCall of message.tool_calls ?? []) {
      if (toolCall.name !== "write_file" && toolCall.name !== "str_replace") {
        continue;
      }

      if (
        toolCall.id &&
        !isSuccessfulToolCallResult(toolResults.get(toolCall.id))
      ) {
        continue;
      }

      const args = toolCall.args as WriteFileToolArgs | StrReplaceToolArgs;
      if (typeof args.path !== "string") {
        continue;
      }

      const normalizedPath = normalizeThreadHistoryFileKey(args.path);
      const previousContent = latestContentByPath.get(normalizedPath);
      let nextContent: string | null = null;

      if (toolCall.name === "write_file") {
        const writeFileContent = (args as WriteFileToolArgs).content;
        if (typeof writeFileContent !== "string") {
          continue;
        }
        nextContent = writeFileContent;
      }

      if (toolCall.name === "str_replace") {
        const strReplaceArgs = args as StrReplaceToolArgs;
        if (
          typeof previousContent !== "string" ||
          typeof strReplaceArgs.old_str !== "string" ||
          typeof strReplaceArgs.new_str !== "string"
        ) {
          continue;
        }

        nextContent = applyStringReplacement({
          content: previousContent,
          oldStr: strReplaceArgs.old_str,
          newStr: strReplaceArgs.new_str,
          replaceAll: strReplaceArgs.replace_all === true,
        });
      }

      if (typeof nextContent !== "string") {
        continue;
      }

      sequence += 1;
      const version = (history[normalizedPath]?.length ?? 0) + 1;
      const snapshot: ThreadFileHistorySnapshot = {
        id: toolCall.id ?? `${message.id ?? normalizedPath}:${sequence}`,
        filepath: args.path,
        normalizedPath,
        version,
        sequence,
        operation: toolCall.name,
        description:
          typeof args.description === "string" ? args.description : undefined,
        content: nextContent,
        previousContent,
        messageId: message.id,
        toolCallId: toolCall.id,
      };

      history[normalizedPath] ??= [];
      history[normalizedPath].push(snapshot);
      latestContentByPath.set(normalizedPath, nextContent);
    }
  }

  return history;
}

export function getThreadFileHistorySnapshots(
  messages: Message[],
  filepath: string,
) {
  const normalizedPath = normalizeThreadHistoryFileKey(filepath);
  return buildThreadFileHistory(messages)[normalizedPath] ?? [];
}
