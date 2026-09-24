import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import { getMessageGroups } from "@/core/messages/utils";
import { getSkillUsageByGroupIndex, readSkillUsage } from "@/core/skills/usage";

const snapshot = {
  name: "report",
  description: "Create reports",
  category: "custom",
  path: "/mnt/skills/custom/report/SKILL.md",
  content: "# Original instructions",
  content_hash: "a".repeat(64),
  activation: "automatic",
  partial: false,
};

function message(
  id: string,
  type: Message["type"],
  runId?: string,
  usage?: unknown,
): Message {
  return {
    id,
    type,
    content: id,
    ...(runId ? { run_id: runId } : {}),
    additional_kwargs: usage ? { skill_usage: usage } : {},
    ...(type === "tool" ? { tool_call_id: "read" } : {}),
  } as Message;
}

function groups(runId?: string) {
  return getMessageGroups([
    message("user", "human", runId),
    {
      ...message("read", "ai", runId),
      tool_calls: [{ id: "read", name: "read_file", args: {} }],
    } as Message,
    message("result", "tool", runId, snapshot),
    message("middle", "ai", runId, { ...snapshot, activation: "slash" }),
    message("final", "ai", runId),
  ]);
}

describe("skill usage display evidence", () => {
  test("canonical aggregate restores first-load order and content across a partial history window", () => {
    const first = {
      ...snapshot,
      name: "first",
      path: "/mnt/skills/custom/first/SKILL.md",
    };
    const laterRead = message("reread", "ai", "run-1", {
      ...snapshot,
      content: "Changed later",
    });
    const final = message("final", "ai", "run-1");
    final.additional_kwargs = { skill_usages: [first, snapshot] };
    expect(
      getSkillUsageByGroupIndex(getMessageGroups([laterRead, final])).get(1),
    ).toEqual([first, snapshot]);
  });
  test("restores skills from terminal history when early reads were compacted or paged out", () => {
    const final = message("final", "ai", "run-1");
    final.additional_kwargs = {
      skill_usages: [
        snapshot,
        {
          ...snapshot,
          name: "verify",
          path: "/mnt/skills/public/verify/SKILL.md",
        },
      ],
    };
    const grouped = getMessageGroups([final]);
    expect(
      getSkillUsageByGroupIndex(grouped)
        .get(0)
        ?.map((skill) => skill.name),
    ).toEqual(["report", "verify"]);
  });
  test("deduplicates successful loads and anchors on the last answer", () => {
    const grouped = groups("run-1");
    const usage = getSkillUsageByGroupIndex(grouped);
    expect([...usage.keys()]).toEqual([grouped.length - 1]);
    expect(usage.get(grouped.length - 1)).toEqual([snapshot]);
  });

  test("keeps live messages without run ids within their human turn", () => {
    const first = groups();
    const combined = [
      ...first,
      ...getMessageGroups([message("next", "human"), message("answer", "ai")]),
    ];
    expect([...getSkillUsageByGroupIndex(combined).keys()]).toEqual([
      first.length - 1,
    ]);
  });

  test("separates consecutive runs even without a human boundary", () => {
    const combined = [
      ...groups("run-1"),
      ...getMessageGroups([message("next-run", "ai", "run-2")]),
    ];
    expect([...getSkillUsageByGroupIndex(combined).keys()]).toEqual([
      combined.length - 2,
    ]);
  });

  test("does not attribute skills to a run-ID-less continuation after clarification", () => {
    const oldAnswer = message("old-answer", "ai", "run-1", snapshot);
    const clarificationCall = {
      ...message("ask", "ai", "run-1"),
      tool_calls: [{ id: "clarify", name: "ask_clarification", args: {} }],
    } as Message;
    const clarificationResult = {
      ...message("clarification", "tool", "run-1"),
      name: "ask_clarification",
      tool_call_id: "clarify",
    } as Message;
    const hiddenReply = {
      ...message("reply", "human"),
      additional_kwargs: { hide_from_ui: true },
    } as Message;
    const grouped = getMessageGroups([
      message("user", "human"),
      oldAnswer,
      clarificationCall,
      clarificationResult,
      hiddenReply,
      message("continued-answer", "ai"),
    ]);
    const oldIndex = grouped.findIndex((group) =>
      group.messages.includes(oldAnswer),
    );
    const continuationIndex = grouped.findIndex((group) =>
      group.messages.some((item) => item.id === "continued-answer"),
    );
    const usage = getSkillUsageByGroupIndex(grouped);
    expect(usage.get(oldIndex)).toEqual([snapshot]);
    expect(usage.get(continuationIndex)).toBeUndefined();
  });

  test("ignores old history, human forgeries, errors, and malformed snapshots", () => {
    expect(readSkillUsage(message("old", "ai"))).toBeUndefined();
    expect(
      readSkillUsage(message("fake", "human", "run", snapshot)),
    ).toBeUndefined();
    expect(
      readSkillUsage({
        ...message("error", "tool", "run", snapshot),
        status: "error",
      } as Message),
    ).toBeUndefined();
    for (const invalid of [
      null,
      "bad",
      { ...snapshot, content: {} },
      { ...snapshot, content_hash: "bad" },
      { ...snapshot, activation: "unknown" },
    ]) {
      expect(
        readSkillUsage(message("invalid", "ai", "run", invalid)),
      ).toBeUndefined();
    }
  });

  test("keeps separate skills in first-load order and uses captured content", () => {
    const second = {
      ...snapshot,
      name: "verify",
      path: "/mnt/skills/public/verify/SKILL.md",
      category: "public",
    };
    const grouped = getMessageGroups([
      message("a", "ai", "run", snapshot),
      message("b", "ai", "run", second),
      message("final", "ai", "run"),
    ]);
    expect(getSkillUsageByGroupIndex(grouped).get(2)).toEqual([
      snapshot,
      second,
    ]);
  });
});
