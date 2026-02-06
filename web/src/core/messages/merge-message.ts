// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { parse as bestEffortParse } from "best-effort-json-parser";

import type {
  ChatEvent,
  InterruptEvent,
  MessageChunkEvent,
  ToolCallChunksEvent,
  ToolCallResultEvent,
  ToolCallsEvent,
} from "../api";
import { deepClone } from "../utils/deep-clone";

import type { Message } from "./types";

/**
 * Safely parse JSON from streamed tool call argument chunks.
 * Uses best-effort-json-parser to handle incomplete JSON from streaming.
 * This addresses issue #528 where MCP tool call arguments may be incomplete
 * when using stream_mode="messages".
 */
function safeParseToolArgs(argsString: string): Record<string, unknown> {
  try {
    // First try standard JSON.parse for complete JSON
    return JSON.parse(argsString) as Record<string, unknown>;
  } catch {
    // If standard parsing fails, use best-effort parser for incomplete JSON
    try {
      const result = bestEffortParse(argsString);
      // Ensure we return an object
      if (result && typeof result === "object" && !Array.isArray(result)) {
        return result as Record<string, unknown>;
      }
      // If parsing returns something unexpected, wrap in an object
      return { _parsed: result };
    } catch {
      // If all parsing fails, return empty object
      console.warn("Failed to parse tool call arguments:", argsString);
      return {};
    }
  }
}

export function mergeMessage(message: Message, event: ChatEvent) {
  if (event.type === "message_chunk") {
    mergeTextMessage(message, event);
  } else if (event.type === "tool_calls" || event.type === "tool_call_chunks") {
    mergeToolCallMessage(message, event);
  } else if (event.type === "tool_call_result") {
    mergeToolCallResultMessage(message, event);
  } else if (event.type === "interrupt") {
    mergeInterruptMessage(message, event);
  }
  if (event.type !== "citations" && event.type !== "error" && event.data.finish_reason) {
    message.finishReason = event.data.finish_reason;
    message.isStreaming = false;
    if (message.toolCalls) {
      message.toolCalls.forEach((toolCall) => {
        if (toolCall.argsChunks?.length) {
          toolCall.args = safeParseToolArgs(toolCall.argsChunks.join(""));
          delete toolCall.argsChunks;
        }
        // Handle direct_response tool: extract message content for display
        if (toolCall.name === "direct_response" && toolCall.args?.message) {
          message.content = toolCall.args.message as string;
          message.contentChunks = [message.content];
        }
      });
    }
  }
  return deepClone(message);
}

function mergeTextMessage(message: Message, event: MessageChunkEvent) {
  if (event.data.content) {
    message.content += event.data.content;
    message.contentChunks.push(event.data.content);
  }
  if (event.data.reasoning_content) {
    message.reasoningContent = (message.reasoningContent ?? "") + event.data.reasoning_content;
    message.reasoningContentChunks = message.reasoningContentChunks ?? [];
    message.reasoningContentChunks.push(event.data.reasoning_content);
  }
}
function convertToolChunkArgs(args: string) {
  // Convert escaped characters in args
  if (!args) return "";
  return args.replace(/&#91;/g, "[").replace(/&#93;/g, "]").replace(/&#123;/g, "{").replace(/&#125;/g, "}");
}
function mergeToolCallMessage(
  message: Message,
  event: ToolCallsEvent | ToolCallChunksEvent,
) {
  if (event.type === "tool_calls" && event.data.tool_calls[0]?.name) {
    message.toolCalls = event.data.tool_calls.map((raw) => ({
      id: raw.id,
      name: raw.name,
      args: raw.args,
      result: undefined,
    }));
  }

  message.toolCalls ??= [];
  for (const chunk of event.data.tool_call_chunks) {
    if (chunk.id) {
      const toolCall = message.toolCalls.find(
        (toolCall) => toolCall.id === chunk.id,
      );
      if (toolCall) {
        toolCall.argsChunks = [convertToolChunkArgs(chunk.args)];
      }
    } else {
      const streamingToolCall = message.toolCalls.find(
        (toolCall) => toolCall.argsChunks?.length,
      );
      if (streamingToolCall) {
        streamingToolCall.argsChunks!.push(convertToolChunkArgs(chunk.args));
      }
    }
  }
}

function mergeToolCallResultMessage(
  message: Message,
  event: ToolCallResultEvent,
) {
  const toolCall = message.toolCalls?.find(
    (toolCall) => toolCall.id === event.data.tool_call_id,
  );
  if (toolCall) {
    toolCall.result = event.data.content;
  }
}

function mergeInterruptMessage(message: Message, event: InterruptEvent) {
  message.isStreaming = false;
  message.options = event.data.options;
}
