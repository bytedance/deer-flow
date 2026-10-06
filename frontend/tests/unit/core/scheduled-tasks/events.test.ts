import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import { enUS, zhCN } from "@/core/i18n";
import {
  describeTaskEvent,
  placeTaskEvents,
  SCHEDULED_TASK_LIFECYCLE_EVENTS,
  sentenceGap,
  SCHEDULED_TASK_LIFECYCLE_REASONS,
  type ScheduledTaskEvent,
} from "@/core/scheduled-tasks/events";

import { expectNoRawIdentifiers } from "../../helpers/readable";

const CONTRACT = JSON.parse(
  readFileSync(
    resolve(
      __dirname,
      "../../../../../contracts/scheduled_goal_notes_contract.json",
    ),
    "utf-8",
  ),
) as {
  version: number;
  lifecycle_events: string[];
  lifecycle_reasons: Record<string, string[]>;
};

const TASK_ID = "4f1c2b9e-1d2c-4a5b-9c8d-7e6f5a4b3c2d";
const RUN_THREAD_ID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";

function event(overrides: Partial<ScheduledTaskEvent>): ScheduledTaskEvent {
  return {
    id: "evt-0123456789abcdef0123456789abcdef",
    task_id: TASK_ID,
    event: "task_stopped",
    reason_code: "agent_stop",
    task_title: "Check the release checklist",
    stop_condition: null,
    run_thread_id: RUN_THREAD_ID,
    run_number: 3,
    run_status: "success",
    max_runs: null,
    end_at: null,
    schedule_type: "interval",
    after_run_id: null,
    created_at: "2026-10-06T08:00:00Z",
    ...overrides,
  };
}

/** One example per lifecycle reason (and the variants the copy distinguishes). */
const CASES: Array<[string, Partial<ScheduledTaskEvent>]> = [
  ["stopped with condition", { stop_condition: "all items are ticked" }],
  ["stopped without condition", {}],
  [
    "auto-paused",
    {
      event: "task_paused",
      reason_code: "consecutive_unmet",
      run_status: "unmet",
    },
  ],
  [
    "finished: max runs",
    { event: "task_finished", reason_code: "max_runs", max_runs: 5 },
  ],
  [
    "finished: end time",
    {
      event: "task_finished",
      reason_code: "end_at",
      end_at: "2026-10-06T07:59:00Z",
    },
  ],
  [
    "once done",
    { event: "task_finished", reason_code: "once_done", schedule_type: "once" },
  ],
  [
    "once failed",
    {
      event: "task_finished",
      reason_code: "once_failed",
      schedule_type: "once",
      run_status: "failed",
    },
  ],
];

const CJK = /[一-鿿]/;

describe("describeTaskEvent", () => {
  test.each(CASES)(
    "%s reads naturally in English and Chinese",
    (_, overrides) => {
      const en = describeTaskEvent(event(overrides), enUS)!;
      const zh = describeTaskEvent(event(overrides), zhCN)!;
      for (const description of [en, zh]) {
        expect(description).not.toBeNull();
        expectNoRawIdentifiers(description.text);
        expect(description.text).not.toMatch(
          /task_(stopped|paused|finished)|agent_stop|consecutive_unmet|once_(done|failed)|evt-|\{|\}/,
        );
        expect(description.text).toContain(
          overrides.task_title ?? "Check the release checklist",
        );
        expect(
          description.segments.filter((segment) => segment.kind === "title"),
        ).toEqual([{ kind: "title", text: "Check the release checklist" }]);
      }
      expect(zh.text).toMatch(CJK);
      expect(en.text).not.toMatch(CJK);
    },
  );

  test("a pause by the agent shows the stop condition as its own segment and links the run", () => {
    const description = describeTaskEvent(
      event({ stop_condition: "  all items are ticked " }),
      enUS,
    )!;
    expect(description.kind).toBe("stopped");
    expect(description.text).toBe(
      "Check the release checklist was paused by the agent. Stop condition met: all items are ticked",
    );
    expect(description.condition).toBe("all items are ticked");
    expect(description.segments.at(-1)).toEqual({
      kind: "condition",
      text: "all items are ticked",
    });
    expect(description.action).toEqual({
      kind: "seeThatRun",
      label: "See that run",
      href: `/workspace/chats/${RUN_THREAD_ID}`,
    });
  });

  test("without a run chat (a skipped occurrence) the line offers Open task", () => {
    const description = describeTaskEvent(
      event({ run_thread_id: null }),
      zhCN,
    )!;
    expect(description.action).toEqual({
      kind: "openTask",
      label: zhCN.scheduledTasks.actions.openTask,
      href: `/workspace/scheduled-tasks?task_id=${TASK_ID}`,
    });
  });

  test("finished and auto-paused lines open the task", () => {
    for (const [, overrides] of CASES.slice(2, 5)) {
      expect(describeTaskEvent(event(overrides), enUS)!.action.kind).toBe(
        "openTask",
      );
    }
    for (const [, overrides] of CASES.slice(5)) {
      expect(describeTaskEvent(event(overrides), enUS)!.action.kind).toBe(
        "seeThatRun",
      );
    }
  });

  test("the max-runs line names the cap", () => {
    expect(
      describeTaskEvent(
        event({ event: "task_finished", reason_code: "max_runs", max_runs: 5 }),
        enUS,
      )!.text,
    ).toBe("Check the release checklist finished: all 5 runs are done.");
    expect(
      describeTaskEvent(
        event({ event: "task_finished", reason_code: "max_runs", max_runs: 5 }),
        zhCN,
      )!.text,
    ).toBe("Check the release checklist 已结束：5 次运行已全部完成。");
  });

  test("in Chinese, a Chinese title takes no space before the predicate; a Latin one does", () => {
    const finished = {
      event: "task_finished",
      reason_code: "max_runs",
      max_runs: 5,
    } as const;
    expect(
      describeTaskEvent(
        event({ ...finished, task_title: "检查发布清单" }),
        zhCN,
      )!.text,
    ).toBe("检查发布清单已结束：5 次运行已全部完成。");
    expect(
      describeTaskEvent(event({ ...finished, task_title: "Release v2" }), zhCN)!
        .text,
    ).toBe("Release v2 已结束：5 次运行已全部完成。");
    expect(
      describeTaskEvent(event({ ...finished, task_title: "  " }), zhCN)!.text,
    ).toBe("未命名任务已结束：5 次运行已全部完成。");
  });

  test("a stop or finish adds the last run's outcome as a separate sentence", () => {
    const stoppedFailed = describeTaskEvent(
      event({ run_status: "failed" }),
      enUS,
    )!;
    expect(stoppedFailed.suffix).toBe("The last run failed.");
    expect(stoppedFailed.text).toBe(
      "Check the release checklist was paused by the agent: its stop condition was met. The last run failed.",
    );
    expect(
      describeTaskEvent(event({ run_status: "interrupted" }), zhCN)!.text,
    ).toBe(
      "Check the release checklist 已由智能体暂停：停止条件已满足。最后一次运行被中断了。",
    );
    const finishedUnmet = describeTaskEvent(
      event({
        event: "task_finished",
        reason_code: "end_at",
        run_status: "unmet",
      }),
      zhCN,
    )!;
    expect(finishedUnmet.suffix).toBe("最后一次运行未达成目标。");
    // "Interrupted" is said on stopped lines only.
    expect(
      describeTaskEvent(
        event({
          event: "task_finished",
          reason_code: "max_runs",
          max_runs: 2,
          run_status: "interrupted",
        }),
        enUS,
      )!.suffix,
    ).toBeNull();
    expect(describeTaskEvent(event({}), enUS)!.suffix).toBeNull();
  });

  test("a suffix after a bare stop condition gets its own stop", () => {
    const stopped = {
      stop_condition: "the report is published",
      run_status: "failed" as const,
    };
    expect(describeTaskEvent(event(stopped), enUS)!.text).toBe(
      "Check the release checklist was paused by the agent. Stop condition met: the report is published. The last run failed.",
    );
    expect(
      describeTaskEvent(
        event({ stop_condition: "报告已发布", run_status: "unmet" }),
        zhCN,
      )!.text,
    ).toBe(
      "Check the release checklist 已由智能体暂停。停止条件已满足：报告已发布。最后一次运行未达成目标。",
    );
    expect(sentenceGap("条件：done.", "最后一次运行出错了。")).toBe(" ");
    expect(sentenceGap("条件：已完成。", "The last run failed.")).toBe(" ");
    expect(sentenceGap("met: it is “done!”", "The last run failed.")).toBe(" ");
    expect(sentenceGap("met: done", "The last run failed.")).toBe(". ");
  });

  test("once lines never add a last-run suffix", () => {
    expect(
      describeTaskEvent(
        event({
          event: "task_finished",
          reason_code: "once_failed",
          run_status: "failed",
        }),
        enUS,
      ),
    ).toMatchObject({
      kind: "onceFailed",
      suffix: null,
      text: "Check the release checklist didn't finish.",
    });
  });

  test("a missing title reads as an untitled task, never the id", () => {
    for (const [t, untitled] of [
      [enUS, "Untitled task"],
      [zhCN, "未命名任务"],
    ] as const) {
      const description = describeTaskEvent(event({ task_title: "   " }), t)!;
      expect(description.segments[0]).toEqual({
        kind: "title",
        text: untitled,
      });
      expect(description.text).not.toContain(TASK_ID);
    }
  });

  test("a finish with a reason this client does not know still reads", () => {
    expect(
      describeTaskEvent(
        event({ event: "task_finished", reason_code: "budget_spent" }),
        enUS,
      )!.text,
    ).toBe("Check the release checklist finished.");
  });

  test("an unknown event is not rendered", () => {
    expect(
      describeTaskEvent(event({ event: "task_archived" }), enUS),
    ).toBeNull();
  });

  test("lifecycle names equal contract v3", () => {
    expect(CONTRACT.version).toBeGreaterThanOrEqual(3);
    expect([...SCHEDULED_TASK_LIFECYCLE_EVENTS]).toEqual(
      CONTRACT.lifecycle_events,
    );
    expect(
      Object.fromEntries(
        Object.entries(SCHEDULED_TASK_LIFECYCLE_REASONS).map(([key, value]) => [
          key,
          [...value],
        ]),
      ),
    ).toEqual(CONTRACT.lifecycle_reasons);
  });

  test("every contract reason has copy", () => {
    for (const [name, reasons] of Object.entries(CONTRACT.lifecycle_reasons)) {
      for (const reason of reasons) {
        expect(
          describeTaskEvent(
            event({ event: name, reason_code: reason, max_runs: 4 }),
            zhCN,
          ),
        ).not.toBeNull();
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Placement
// ---------------------------------------------------------------------------

type Group = { type: string; messages: Message[] };

function message(type: "human" | "ai", runId?: string): Message {
  return {
    type,
    content: "x",
    ...(runId ? { run_id: runId } : {}),
  } as unknown as Message;
}

function group(type: string, ...messages: Message[]): Group {
  return { type, messages };
}

// Turn 1: human (run-1) → processing → assistant; turn 2: human (run-2) → assistant.
const GROUPS: Group[] = [
  group("human", message("human", "run-1")),
  group("assistant:processing", message("ai", "run-1")),
  group("assistant", message("ai", "run-1")),
  group("human", message("human", "run-2")),
  group("assistant", message("ai", "run-2")),
];

describe("placeTaskEvents", () => {
  test("an event goes at the end of its anchor run's turn, before the next human group", () => {
    const placed = placeTaskEvents(GROUPS, [
      event({ id: "e-1", after_run_id: "run-1" }),
    ]);
    expect([...placed.afterGroup.keys()]).toEqual([2]);
    expect(placed.tail).toEqual([]);
  });

  test("an anchor found only in a processing group still ends with its turn", () => {
    const groups = [
      group("human", message("human")),
      group("assistant:processing", message("ai", "run-7")),
      group("assistant:scheduled-task", message("ai")),
      group("assistant", message("ai")),
      group("human", message("human")),
    ];
    const placed = placeTaskEvents(groups, [
      event({ id: "e-1", after_run_id: "run-7" }),
    ]);
    expect([...placed.afterGroup.keys()]).toEqual([3]);
  });

  test("an anchor no message carries (or no anchor) goes after the last group", () => {
    const placed = placeTaskEvents(GROUPS, [
      event({ id: "e-1", after_run_id: "run-pruned" }),
      event({ id: "e-2", after_run_id: null }),
    ]);
    expect([...placed.afterGroup.keys()]).toEqual([4]);
    expect(placed.afterGroup.get(4)!.map((item) => item.id)).toEqual([
      "e-1",
      "e-2",
    ]);
  });

  test("while older history is unloaded, a missing anchor is held back, not put at the bottom", () => {
    const placed = placeTaskEvents(
      GROUPS,
      [
        event({ id: "e-old", after_run_id: "run-on-older-page" }),
        event({ id: "e-loaded", after_run_id: "run-1" }),
        event({ id: "e-none", after_run_id: null }),
      ],
      { hasMoreHistory: true },
    );
    expect(placed.afterGroup.get(2)!.map((item) => item.id)).toEqual([
      "e-loaded",
    ]);
    expect(placed.afterGroup.get(4)!.map((item) => item.id)).toEqual([
      "e-none",
    ]);
    const all = [...placed.afterGroup.values()].flat().concat(placed.tail);
    expect(all.map((item) => item.id)).not.toContain("e-old");
  });

  test("with no groups loaded yet and more history, anchored events wait", () => {
    const placed = placeTaskEvents(
      [],
      [
        event({ id: "anchored", after_run_id: "run-1" }),
        event({ id: "free", after_run_id: null }),
      ],
      { hasMoreHistory: true },
    );
    expect(placed.tail.map((item) => item.id)).toEqual(["free"]);
  });

  test("events at one position are ordered by created_at", () => {
    const placed = placeTaskEvents(GROUPS, [
      event({
        id: "late",
        after_run_id: "run-2",
        created_at: "2026-10-06T09:00:00Z",
      }),
      event({
        id: "early",
        after_run_id: "run-2",
        created_at: "2026-10-06T08:00:00Z",
      }),
      event({
        id: "missing-anchor",
        after_run_id: "gone",
        created_at: "2026-10-06T08:30:00Z",
      }),
    ]);
    expect(placed.afterGroup.get(4)!.map((item) => item.id)).toEqual([
      "early",
      "missing-anchor",
      "late",
    ]);
  });

  test("with no groups at all every event is a tail line", () => {
    const placed = placeTaskEvents(
      [],
      [
        event({ id: "b", created_at: "2026-10-06T09:00:00Z" }),
        event({ id: "a", created_at: "2026-10-06T08:00:00Z" }),
      ],
    );
    expect(placed.afterGroup.size).toBe(0);
    expect(placed.tail.map((item) => item.id)).toEqual(["a", "b"]);
  });
});
