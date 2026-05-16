import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it, vi } from "vitest";

import {
  extractBlockIdsFromMessages,
  extractResolvedBlockIdsFromMessages,
  fetchResolvedBlockHistory,
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

  it("delegates block history resolution to the backend extract API", async () => {
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

    vi.stubGlobal("fetch", () =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            blocks: [
              {
                block_id: "daily-report-chart__1",
                component: "card",
                props: { title: "Round 1" },
              },
              {
                block_id: "daily-report-chart__2",
                component: "card",
                props: { title: "Round 2" },
              },
            ],
            blockIdsByMessageKey: {
              "tool-1": ["daily-report-chart__1"],
              "tool-2": ["daily-report-chart__2"],
            },
            duplicatedRawBlockIds: ["daily-report-chart"],
          }),
      }),
    );

    const resolved = await fetchResolvedBlockHistory("thread-1", messages);

    expect(resolved.blocks.map((block) => block.block_id)).toEqual([
      "daily-report-chart__1",
      "daily-report-chart__2",
    ]);
    expect(resolved.duplicatedRawBlockIds.has("daily-report-chart")).toBe(true);
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
