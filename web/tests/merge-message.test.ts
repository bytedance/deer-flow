// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

/**
 * Tests for Issue #528 Fix: MCP Tool Call Argument Parsing
 *
 * These tests verify:
 * - Complete JSON tool call arguments parsing
 * - Incomplete JSON tool call arguments handling (using best-effort-json-parser)
 * - Multiple argument chunks merging
 * - Escaped character conversion in tool call arguments
 */

import { mergeMessage } from "../src/core/messages/merge-message";
import type { Message, ToolCallRuntime } from "../src/core/messages/types";
import type {
  ChatEvent,
  ToolCallChunksEvent,
  ToolCallsEvent,
} from "../src/core/api/types";

function createBaseMessage(): Message {
  return {
    id: "test-msg-1",
    threadId: "thread-1",
    role: "assistant",
    content: "",
    contentChunks: [],
    isStreaming: true,
    agent: "researcher",
  };
}

function createToolCall(
  overrides: Partial<ToolCallRuntime> & { id: string; name: string }
): ToolCallRuntime {
  return {
    args: {},
    ...overrides,
  };
}

describe("mergeMessage", () => {
  describe("tool call argument parsing", () => {
    it("should parse complete JSON tool call arguments", () => {
      const message = createBaseMessage();
      message.toolCalls = [
        createToolCall({
          id: "call-1",
          name: "search",
          argsChunks: ['{"query": "test query"}'],
        }),
      ];

      const event: ChatEvent = {
        type: "message_chunk",
        data: {
          id: "test-msg-1",
          thread_id: "thread-1",
          agent: "researcher",
          role: "assistant",
          finish_reason: "tool_calls",
        },
      };

      const result = mergeMessage(message, event);
      expect(result.toolCalls?.[0]?.args).toEqual({ query: "test query" });
      expect(result.toolCalls?.[0]?.argsChunks).toBeUndefined();
    });

    it("should handle incomplete JSON tool call arguments (issue #528)", () => {
      const message = createBaseMessage();
      // Simulate incomplete JSON from streaming - missing closing brace
      message.toolCalls = [
        createToolCall({
          id: "call-1",
          name: "search",
          argsChunks: ['{"query": "test query"'],
        }),
      ];

      const event: ChatEvent = {
        type: "message_chunk",
        data: {
          id: "test-msg-1",
          thread_id: "thread-1",
          agent: "researcher",
          role: "assistant",
          finish_reason: "tool_calls",
        },
      };

      // Should not throw an error and should attempt to parse
      const result = mergeMessage(message, event);
      expect(result.toolCalls?.[0]?.args).toBeDefined();
      expect(result.toolCalls?.[0]?.argsChunks).toBeUndefined();
    });

    it("should handle multiple argument chunks", () => {
      const message = createBaseMessage();
      message.toolCalls = [
        createToolCall({
          id: "call-1",
          name: "search",
          argsChunks: ['{"query":', ' "test', ' query"', "}"],
        }),
      ];

      const event: ChatEvent = {
        type: "message_chunk",
        data: {
          id: "test-msg-1",
          thread_id: "thread-1",
          agent: "researcher",
          role: "assistant",
          finish_reason: "tool_calls",
        },
      };

      const result = mergeMessage(message, event);
      expect(result.toolCalls?.[0]?.args).toEqual({ query: "test query" });
    });

    it("should handle incomplete nested JSON", () => {
      const message = createBaseMessage();
      // Simulate incomplete nested JSON from streaming
      message.toolCalls = [
        createToolCall({
          id: "call-1",
          name: "complex_tool",
          argsChunks: ['{"query": "test", "options": {"limit": 10'],
        }),
      ];

      const event: ChatEvent = {
        type: "message_chunk",
        data: {
          id: "test-msg-1",
          thread_id: "thread-1",
          agent: "researcher",
          role: "assistant",
          finish_reason: "tool_calls",
        },
      };

      // Should not throw an error
      const result = mergeMessage(message, event);
      expect(result.toolCalls?.[0]?.args).toBeDefined();
      expect(result.toolCalls?.[0]?.argsChunks).toBeUndefined();
    });

    it("should handle empty args string gracefully", () => {
      const message = createBaseMessage();
      message.toolCalls = [
        createToolCall({
          id: "call-1",
          name: "simple_tool",
          argsChunks: [""],
        }),
      ];

      const event: ChatEvent = {
        type: "message_chunk",
        data: {
          id: "test-msg-1",
          thread_id: "thread-1",
          agent: "researcher",
          role: "assistant",
          finish_reason: "tool_calls",
        },
      };

      // Should not throw an error
      const result = mergeMessage(message, event);
      expect(result.toolCalls?.[0]?.args).toBeDefined();
    });

    it("should handle MCP tool call with complex arguments", () => {
      const message = createBaseMessage();
      // Simulate MCP tool with complex arguments, partially streamed
      message.toolCalls = [
        createToolCall({
          id: "call-1",
          name: "mcp_github_tool",
          argsChunks: [
            '{"repo": "bytedance/deer-flow", "action": "get_trending", "params": {"limit": 5, "language": "python"',
          ],
        }),
      ];

      const event: ChatEvent = {
        type: "message_chunk",
        data: {
          id: "test-msg-1",
          thread_id: "thread-1",
          agent: "researcher",
          role: "assistant",
          finish_reason: "tool_calls",
        },
      };

      const result = mergeMessage(message, event);
      const args = result.toolCalls?.[0]?.args;
      expect(args).toBeDefined();
      // The best-effort parser should recover the available data
      expect(args?.repo).toBe("bytedance/deer-flow");
    });
  });

  describe("tool call chunks merging", () => {
    it("should accumulate tool call chunks", () => {
      const message = createBaseMessage();

      // First chunk with tool call ID
      const event1: ToolCallsEvent = {
        type: "tool_calls",
        data: {
          id: "test-msg-1",
          thread_id: "thread-1",
          agent: "researcher",
          role: "assistant",
          tool_calls: [
            {
              type: "tool_call",
              id: "call-1",
              name: "search",
              args: { query: "test" },
            },
          ],
          tool_call_chunks: [
            {
              type: "tool_call_chunk",
              index: 0,
              id: "call-1",
              name: "search",
              args: '&#123;"query": "test"&#125;',
            },
          ],
        },
      };

      const result1 = mergeMessage(message, event1);
      expect(result1.toolCalls).toBeDefined();
      expect(result1.toolCalls?.length).toBe(1);
    });

    it("should convert escaped characters in args", () => {
      const message = createBaseMessage();
      message.toolCalls = [
        createToolCall({
          id: "call-1",
          name: "search",
        }),
      ];

      const event: ToolCallChunksEvent = {
        type: "tool_call_chunks",
        data: {
          id: "test-msg-1",
          thread_id: "thread-1",
          agent: "researcher",
          role: "assistant",
          tool_call_chunks: [
            {
              type: "tool_call_chunk",
              index: 0,
              id: "call-1",
              name: "search",
              args: "&#123;&#91;test&#93;&#125;",
            },
          ],
        },
      };

      const result = mergeMessage(message, event);
      // The argsChunks should have converted the escaped chars
      expect(result.toolCalls?.[0]?.argsChunks?.[0]).toBe("{[test]}");
    });
  });
});
