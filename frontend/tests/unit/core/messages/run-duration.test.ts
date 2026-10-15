import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  formatRunDuration,
  getRunDurationDisplaysByGroupIndex,
} from "@/core/messages/run-duration";
import { getMessageGroups } from "@/core/messages/utils";

function message(
  id: string,
  type: Message["type"],
  content: string,
  runId?: string,
  duration?: unknown,
): Message {
  return {
    id,
    type,
    content,
    ...(runId ? { run_id: runId } : {}),
    ...(type === "ai" && duration !== undefined
      ? { additional_kwargs: { turn_duration: duration } }
      : {}),
  } as Message;
}

describe("run duration display placement", () => {
  test("shows one duration after the final visible group for a multi-step run", () => {
    const groups = getMessageGroups([
      message("human-1", "human", "Research this"),
      {
        ...message("ai-tool-1", "ai", "", "run-1", 114),
        tool_calls: [{ id: "call-1", name: "read_file", args: {} }],
      } as Message,
      {
        ...message("tool-1", "tool", "file contents", "run-1"),
        tool_call_id: "call-1",
      } as Message,
      message("ai-middle", "ai", "Intermediate summary", "run-1", 114),
      {
        ...message("ai-tool-2", "ai", "", "run-1", 114),
        tool_calls: [{ id: "call-2", name: "write_todos", args: {} }],
      } as Message,
      {
        ...message("tool-2", "tool", "todos updated", "run-1"),
        tool_call_id: "call-2",
      } as Message,
      message("ai-final", "ai", "Final answer", "run-1", 114),
    ]);

    expect(
      getRunDurationDisplaysByGroupIndex(groups).map((displays) =>
        displays.map(({ runId, durationSeconds }) => ({
          runId,
          durationSeconds,
        })),
      ),
    ).toEqual([[], [], [], [], [{ runId: "run-1", durationSeconds: 114 }]]);
  });

  test("keeps equal durations independent across runs", () => {
    const groups = getMessageGroups([
      message("human-1", "human", "First"),
      message("ai-1", "ai", "First answer", "run-1", 114),
      message("human-2", "human", "Second"),
      message("ai-2", "ai", "Second answer", "run-2", 114),
    ]);

    expect(getRunDurationDisplaysByGroupIndex(groups)).toEqual([
      [],
      [{ runId: "run-1", durationSeconds: 114 }],
      [],
      [{ runId: "run-2", durationSeconds: 114 }],
    ]);
  });

  test("carries an earlier AI duration to the run's final tool-bearing group", () => {
    const groups = getMessageGroups([
      message("human-1", "human", "Do it"),
      message("ai-answer", "ai", "Initial answer", "run-1", 9),
      {
        ...message("ai-tool", "ai", "", "run-1"),
        tool_calls: [{ id: "call-1", name: "write_todos", args: {} }],
      } as Message,
      {
        ...message("tool-1", "tool", "done", "run-1"),
        tool_call_id: "call-1",
      } as Message,
    ]);

    expect(getRunDurationDisplaysByGroupIndex(groups)).toEqual([
      [],
      [],
      [{ runId: "run-1", durationSeconds: 9 }],
    ]);
  });

  test("keeps zero but ignores missing, negative, and non-finite durations", () => {
    const groups = getMessageGroups([
      message("ai-zero", "ai", "Zero", "run-zero", 0),
      message("ai-missing", "ai", "Missing", "run-missing"),
      message("ai-negative", "ai", "Negative", "run-negative", -1),
      message("ai-infinite", "ai", "Infinite", "run-infinite", Infinity),
    ]);

    expect(getRunDurationDisplaysByGroupIndex(groups)).toEqual([
      [{ runId: "run-zero", durationSeconds: 0 }],
      [],
      [],
      [],
    ]);
  });
});

describe("run duration formatting", () => {
  test("formats sub-second, second, minute, and hour durations in English", () => {
    expect(formatRunDuration(0, enUS.runDuration)).toBe("<1s");
    expect(formatRunDuration(59, enUS.runDuration)).toBe("59s");
    expect(formatRunDuration(114, enUS.runDuration)).toBe("1m 54s");
    expect(formatRunDuration(3723, enUS.runDuration)).toBe("1h 2m 3s");
  });

  test("formats durations in Chinese", () => {
    expect(formatRunDuration(0, zhCN.runDuration)).toBe("不足 1 秒");
    expect(formatRunDuration(114, zhCN.runDuration)).toBe("1 分 54 秒");
    expect(formatRunDuration(3723, zhCN.runDuration)).toBe("1 小时 2 分 3 秒");
  });

  test("rejects invalid durations and floors fractional seconds", () => {
    expect(formatRunDuration(-1, enUS.runDuration)).toBeNull();
    expect(formatRunDuration(Infinity, enUS.runDuration)).toBeNull();
    expect(formatRunDuration(Number.NaN, enUS.runDuration)).toBeNull();
    expect(formatRunDuration(61.9, enUS.runDuration)).toBe("1m 1s");
  });
});
