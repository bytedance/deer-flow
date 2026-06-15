import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/core/api/fetcher", () => ({
  fetch: vi.fn(),
}));

import {
  extractBlocksIncremental,
  extractBlockIdsFromMessages,
  extractResolvedBlockIdsFromMessages,
  getHistoryMessageKey,
} from "@/core/genui/history";
import { fetch as mockFetch } from "@/core/api/fetcher";

const mockedFetch = vi.mocked(mockFetch);

function makeToolMessage(id: string, blockIds: string[]): Message {
  const text = blockIds.map((bid) => `block_id=${bid}`).join(", ");
  return {
    id,
    type: "tool",
    content: text,
    name: "render_ui",
    tool_call_id: `tc-${id}`,
  } as Message;
}

function makeAiMessage(id: string, content: string): Message {
  return {
    id,
    type: "ai",
    content,
  } as Message;
}

describe("incremental extraction (2.8)", () => {
  it("extractBlocksIncremental returns empty for empty messages", async () => {
    const result = await extractBlocksIncremental("thread-1", []);
    expect(result.blocks).toEqual([]);
    expect(result.blockIdsByMessageKey.size).toBe(0);
    expect(result.duplicatedRawBlockIds.size).toBe(0);
  });

  it("extractBlocksIncremental calls the API with only the new messages", async () => {
    const newMessages = [makeToolMessage("tool-1", ["block-a", "block-b"])];

    mockedFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        blocks: [
          { block_id: "block-a", component: "markdown", props: {} },
          { block_id: "block-b", component: "chart", props: {} },
        ],
        blockIdsByMessageKey: { "tool-1": ["block-a", "block-b"] },
        duplicatedRawBlockIds: [],
      }),
    } as Response);

    const result = await extractBlocksIncremental("thread-1", newMessages);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const callUrl = mockedFetch.mock.calls[0]?.[0];
    expect(callUrl).toContain("/api/threads/thread-1/ui-blocks/extract");

    const callBody = JSON.parse(mockedFetch.mock.calls[0]?.[1]?.body as string);
    expect(callBody.messages).toHaveLength(1);
    expect(callBody.messages[0].id).toBe("tool-1");

    expect(result.blocks).toHaveLength(2);
    expect(result.blockIdsByMessageKey.get("tool-1")).toEqual(["block-a", "block-b"]);
  });

  it("incremental produces identical block IDs as full extraction for same messages", async () => {
    const allMessages = [
      makeAiMessage("ai-1", "Let me search"),
      makeToolMessage("tool-1", ["block-x"]),
      makeAiMessage("ai-2", "Here are results"),
    ];

    const fullResponse = {
      ok: true,
      json: async () => ({
        blocks: [{ block_id: "block-x", component: "markdown", props: {} }],
        blockIdsByMessageKey: { "tool-1": ["block-x"] },
        duplicatedRawBlockIds: [],
      }),
    } as Response;

    mockedFetch.mockResolvedValueOnce(fullResponse);
    const fullResult = await extractBlocksIncremental("thread-1", allMessages);

    mockedFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        blocks: [{ block_id: "block-x", component: "markdown", props: {} }],
        blockIdsByMessageKey: { "tool-1": ["block-x"] },
        duplicatedRawBlockIds: [],
      }),
    } as Response);
    const incrementalResult = await extractBlocksIncremental("thread-1", [allMessages[1]!]);

    expect(fullResult.blocks.map((b) => b.block_id)).toEqual(
      incrementalResult.blocks.map((b) => b.block_id),
    );
  });

  it("extractBlockIdsFromMessages finds block_ids in tool messages", () => {
    const messages = [
      makeAiMessage("ai-1", "Hello"),
      makeToolMessage("tool-1", ["block-1", "block-2"]),
      makeToolMessage("tool-2", ["block-3"]),
    ];

    const blockIds = extractBlockIdsFromMessages(messages);
    expect(blockIds).toEqual(["block-1", "block-2", "block-3"]);
  });

  it("extractResolvedBlockIdsFromMessages uses blockIdsByMessageKey when available", () => {
    const messages = [makeToolMessage("tool-1", ["block-a"])];
    const blockIdsByMessageKey = new Map([["tool-1", ["resolved-block-a"]]]);

    const result = extractResolvedBlockIdsFromMessages(messages, blockIdsByMessageKey);
    expect(result).toEqual(["resolved-block-a"]);
  });

  it("extractResolvedBlockIdsFromMessages falls back to regex when key not found", () => {
    const messages = [makeToolMessage("tool-1", ["block-fallback"])];
    const blockIdsByMessageKey = new Map<string, string[]>();

    const result = extractResolvedBlockIdsFromMessages(messages, blockIdsByMessageKey);
    expect(result).toEqual(["block-fallback"]);
  });

  it("getHistoryMessageKey uses message id when available", () => {
    const message = { id: "msg-1", type: "ai", content: "test" } as Message;
    expect(getHistoryMessageKey(message)).toBe("msg-1");
  });

  it("getHistoryMessageKey falls back to tool_call_id for tool messages", () => {
    const message = {
      type: "tool",
      tool_call_id: "tc-1",
      content: "result",
    } as Message;
    expect(getHistoryMessageKey(message)).toBe("tc-1");
  });
});
