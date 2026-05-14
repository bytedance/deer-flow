import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import { extractBlockIdsFromMessages } from "@/core/genui/history";

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
});
