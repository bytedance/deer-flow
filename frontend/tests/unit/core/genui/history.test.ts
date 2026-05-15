import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import {
  buildResolvedBlockHistory,
  extractBlockIdsFromMessages,
  extractResolvedBlockIdsFromMessages,
} from "@/core/genui/history";

describe("GenUI history helpers", () => {
  it("extracts custom render_ui block IDs from tool results", () => {
    const messages = [
      {
        type: "tool",
        id: "tool-1",
        name: "render_ui",
        tool_call_id: "call-1",
        content:
          "UI component 'form' (create) rendered successfully. block_id=daily-report-scope\n<!--ui_block:{}-->",
      },
      {
        type: "tool",
        id: "tool-2",
        name: "render_ui",
        tool_call_id: "call-2",
        content:
          "UI component 'echart' (create) rendered successfully. block_id=report-chart-1\n<!--ui_block:{}-->",
      },
    ] as Message[];

    expect(extractBlockIdsFromMessages(messages)).toEqual([
      "daily-report-scope",
      "report-chart-1",
    ]);
  });

  it("stops block ID extraction before punctuation", () => {
    const messages = [
      {
        type: "tool",
        id: "tool-1",
        name: "render_ui",
        tool_call_id: "call-1",
        content: "rendered successfully. block_id=form-1.",
      },
    ] as Message[];

    expect(extractBlockIdsFromMessages(messages)).toEqual(["form-1"]);
  });

  it("keeps duplicate create block ids as separate historical instances", () => {
    const messages = [
      {
        type: "tool",
        id: "tool-1",
        name: "render_ui",
        tool_call_id: "call-1",
        content:
          "UI component 'card' (create) rendered successfully. block_id=daily-report-chart\n<!--ui_block:{\"schema_version\":\"1.0\",\"type\":\"ui_block\",\"action\":\"create\",\"block_id\":\"daily-report-chart\",\"component\":\"card\",\"props\":{\"title\":\"Round 1\"},\"interactive\":false}-->",
      },
      {
        type: "tool",
        id: "tool-2",
        name: "render_ui",
        tool_call_id: "call-2",
        content:
          "UI component 'card' (create) rendered successfully. block_id=daily-report-chart\n<!--ui_block:{\"schema_version\":\"1.0\",\"type\":\"ui_block\",\"action\":\"create\",\"block_id\":\"daily-report-chart\",\"component\":\"card\",\"props\":{\"title\":\"Round 2\"},\"interactive\":false}-->",
      },
    ] as Message[];

    const resolved = buildResolvedBlockHistory(messages);

    expect(resolved.blocks.map((block) => block.block_id)).toEqual([
      "daily-report-chart__1",
      "daily-report-chart__2",
    ]);
    expect(
      extractResolvedBlockIdsFromMessages(
        [messages[0]!],
        resolved.blockIdsByMessageKey,
      ),
    ).toEqual(["daily-report-chart__1"]);
    expect(
      extractResolvedBlockIdsFromMessages(
        [messages[1]!],
        resolved.blockIdsByMessageKey,
      ),
    ).toEqual(["daily-report-chart__2"]);
  });
});
