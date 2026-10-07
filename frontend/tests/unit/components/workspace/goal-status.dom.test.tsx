import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";

import { GoalStatus } from "@/components/workspace/goal-status";
import { I18nContext } from "@/core/i18n/context";
import type { Locale } from "@/core/i18n/locale";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { GoalState, ThreadGoalOutcome } from "@/core/threads/types";

import { expectNoRawIdentifiers } from "../../helpers/readable";

afterEach(cleanup);

const OBJECTIVE = "Write a three-line summary of README.md";

function makeGoal(overrides: Partial<GoalState> = {}): GoalState {
  return {
    objective: OBJECTIVE,
    status: "active",
    created_at: "2026-10-07T00:00:00Z",
    updated_at: "2026-10-07T00:00:00Z",
    continuation_count: 0,
    max_continuations: 8,
    no_progress_count: 0,
    max_no_progress_continuations: 2,
    ...overrides,
  };
}

function stoodDown(
  code: string,
  overrides: Partial<GoalState> = {},
  reason = "The summary has only two lines.",
): GoalState {
  return makeGoal({
    updated_at: "2026-10-07T00:05:00Z",
    ...overrides,
    last_evaluation: {
      satisfied: false,
      blocker: "goal_not_met_yet",
      reason,
      run_id: "run-1",
      evaluated_at: "2026-10-07T00:05:00Z",
      stand_down_reason: code,
    },
  });
}

function makeOutcome(
  overrides: Partial<ThreadGoalOutcome> = {},
): ThreadGoalOutcome {
  return {
    status: "achieved",
    objective: OBJECTIVE,
    goal_created_at: "2026-10-07T00:00:00Z",
    achieved_at: "2026-10-07T00:09:00Z",
    continuation_count: 1,
    max_continuations: 8,
    reason: "The summary has three lines.",
    relied_on_assumption: false,
    reply_message_id: "ai-2",
    ...overrides,
  };
}

type Props = ComponentProps<typeof GoalStatus>;

const TRANSLATIONS = { "en-US": enUS, "zh-CN": zhCN } as const;

function bar(props: Props, locale: Locale = "en-US") {
  return (
    <I18nContext.Provider
      value={{ locale, setLocale: () => undefined, t: TRANSLATIONS[locale] }}
    >
      <GoalStatus {...props} />
    </I18nContext.Provider>
  );
}

function section() {
  return screen.getByTestId("goal-status");
}

function liveRegion() {
  return section().querySelector('[role="status"]')!;
}

/** The row text a sighted user reads, without the screen-reader-only parts. */
function visibleRowText() {
  const row = section().firstElementChild!;
  return [
    row.textContent,
    screen.queryByTestId("goal-status-detail")?.textContent,
  ]
    .filter(Boolean)
    .join(" | ");
}

type Case = {
  name: string;
  props: Props;
  en: string;
  zh: string;
};

const CASES: Case[] = [
  {
    name: "set",
    props: { goal: makeGoal() },
    en: `Goal${OBJECTIVE}`,
    zh: `目标${OBJECTIVE}`,
  },
  {
    name: "in progress",
    props: { goal: makeGoal(), isRunning: true },
    en: `Goal${OBJECTIVE}In progress`,
    zh: `目标${OBJECTIVE}进行中`,
  },
  {
    name: "continuing",
    props: {
      goal: makeGoal({
        continuation_count: 1,
        last_evaluation: {
          satisfied: false,
          blocker: "goal_not_met_yet",
          reason: "Two lines so far.",
        },
      }),
      isRunning: true,
    },
    en: `Goal${OBJECTIVE}Continuing 1/8`,
    zh: `目标${OBJECTIVE}续跑中 1/8`,
  },
  {
    name: "stopped at the limit",
    props: {
      goal: stoodDown("max_continuations_reached", { continuation_count: 8 }),
    },
    en: `Goal${OBJECTIVE}StoppedDetails | Continuation limit reached · 8/8. It won't auto-continue again. Reply to keep going, or set the goal again with /goal <condition> to start a fresh count (this also starts a new run).`,
    zh: `目标${OBJECTIVE}已停止详情 | 已达到自动续跑上限 8/8，不会再自动续跑。回复即可继续；或用 /goal <完成条件> 重新设置目标，次数从零开始（同时会开始一次新的运行）。`,
  },
  {
    name: "stopped with auto-continue off",
    props: {
      goal: stoodDown("max_continuations_reached", { max_continuations: 0 }),
    },
    en: `Goal${OBJECTIVE}StoppedDetails | Goal check: not met yet. Auto-continue is off for this goal. Reply to keep going.`,
    zh: `目标${OBJECTIVE}已停止详情 | 目标检查：尚未达成。这个目标没有开启自动续跑，回复即可继续。`,
  },
  {
    name: "stopped without progress",
    props: { goal: stoodDown("no_progress_detected") },
    en: `Goal${OBJECTIVE}StoppedDetails | No progress between turns. Reply with what's missing, or rephrase the goal with /goal.`,
    zh: `目标${OBJECTIVE}已停止详情 | 连续几轮没有进展。回复说明还缺什么，或用 /goal 换个说法重新设置目标。`,
  },
  {
    name: "stopped at the token budget",
    props: { goal: stoodDown("token_capped") },
    en: `Goal${OBJECTIVE}StoppedDetails | Token budget reached. Send a message to continue; a new run starts with a fresh budget.`,
    zh: `目标${OBJECTIVE}已停止详情 | 已达到 token 预算。发送消息即可继续，新的运行会重新计算预算。`,
  },
  {
    name: "stopped without evidence (count 0)",
    props: { goal: stoodDown("blocked:missing_evidence") },
    en: `Goal${OBJECTIVE}StoppedDetails | Goal check: evidence missing. Ask it to show the result, or reply with what's left.`,
    zh: `目标${OBJECTIVE}已停止详情 | 目标检查：缺少依据。可以让它把结果展示出来，或回复说明还差什么。`,
  },
  {
    name: "stopped after a failed run",
    props: { goal: stoodDown("blocked:run_failed") },
    en: `Goal${OBJECTIVE}StoppedDetails | Goal check: the run did not finish the work. Check the reply for errors, then send a message to retry.`,
    zh: `目标${OBJECTIVE}已停止详情 | 目标检查：这次运行没有完成任务。先看看回复里的错误，再发送消息重试。`,
  },
  {
    name: "waiting for an answer to the open card",
    props: {
      goal: stoodDown(
        "blocked:needs_user_input",
        {},
        "The turn ended on a question to the user that has not been answered.",
      ),
      hasOpenHumanInputCard: true,
    },
    en: `Goal${OBJECTIVE}Waiting for youDetails | Answer the question above to continue.`,
    zh: `目标${OBJECTIVE}等你回复详情 | 回答上面的问题即可继续。`,
  },
  {
    name: "waiting for missing details",
    props: { goal: stoodDown("blocked:needs_user_input") },
    en: `Goal${OBJECTIVE}Waiting for youDetails | Reply with the missing details to continue.`,
    zh: `目标${OBJECTIVE}等你回复详情 | 回复补充缺少的信息即可继续。`,
  },
  {
    name: "waiting on something external",
    props: { goal: stoodDown("blocked:external_wait") },
    en: `Goal${OBJECTIVE}WaitingDetails | Goal check: waiting on something external. Send a message when it's ready.`,
    zh: `目标${OBJECTIVE}等待中详情 | 目标检查：正在等待外部条件，就绪后发送消息即可继续。`,
  },
  {
    name: "unchecked",
    props: { goal: stoodDown("evaluator_failed") },
    en: `Goal${OBJECTIVE}Couldn't check the goalDetails | Couldn't check the goal; the run itself may be fine. It's checked again after your next message.`,
    zh: `目标${OBJECTIVE}未能检查目标详情 | 未能检查目标，这次运行本身可能没问题。下次发消息后会重新检查。`,
  },
  {
    name: "stopped for an unknown reason",
    props: { goal: stoodDown("blocked:new_reason") },
    en: `Goal${OBJECTIVE}StoppedDetails | Send a message to keep going.`,
    zh: `目标${OBJECTIVE}已停止详情 | 发送消息即可继续。`,
  },
  {
    name: "paused",
    props: {
      goal: makeGoal({
        continuation_count: 2,
        last_evaluation: {
          satisfied: false,
          blocker: "goal_not_met_yet",
          reason: "Two lines so far.",
        },
      }),
    },
    en: `Goal${OBJECTIVE}PausedDetails | Auto-continued 2/8. The run ended before the goal was confirmed. Send a message to check again.`,
    zh: `目标${OBJECTIVE}已暂停详情 | 已自动续跑 2/8 次，运行在确认达成前结束了。发送消息即可重新检查。`,
  },
  {
    name: "met after one follow-up",
    props: { goal: null, outcome: makeOutcome() },
    en: `Goal met${OBJECTIVE}Auto-continued onceDetails`,
    zh: `目标已达成${OBJECTIVE}自动续跑了 1 次详情`,
  },
  {
    name: "met after several follow-ups",
    props: { goal: null, outcome: makeOutcome({ continuation_count: 3 }) },
    en: `Goal met${OBJECTIVE}Auto-continued 3 timesDetails`,
    zh: `目标已达成${OBJECTIVE}自动续跑了 3 次详情`,
  },
  {
    name: "met on the first run",
    props: { goal: null, outcome: makeOutcome({ continuation_count: 0 }) },
    en: `Goal met${OBJECTIVE}Details`,
    zh: `目标已达成${OBJECTIVE}详情`,
  },
  {
    name: "met with an assumption",
    props: {
      goal: null,
      outcome: makeOutcome({
        continuation_count: 0,
        relied_on_assumption: true,
      }),
    },
    en: `Goal met${OBJECTIVE}Assumption madeDetails`,
    zh: `目标已达成${OBJECTIVE}含假设详情`,
  },
];

describe.each(["en-US", "zh-CN"] as const)("GoalStatus in %s", (locale) => {
  it.each(CASES)("$name", ({ props, en, zh }) => {
    render(bar(props, locale));
    expect(visibleRowText()).toBe(locale === "en-US" ? en : zh);
    expectNoRawIdentifiers(section());
  });

  it("renders nothing without a goal or a record", () => {
    const { container } = render(bar({ goal: null }, locale));
    expect(container.textContent).toBe("");
  });
});

describe("GoalStatus details", () => {
  it("toggles the panel with its full objective and the checker's note", () => {
    render(
      bar({
        goal: stoodDown("max_continuations_reached", { continuation_count: 8 }),
      }),
    );
    const toggle = screen.getByRole("button", { name: /Details/ });
    const panel = document.getElementById(
      toggle.getAttribute("aria-controls")!,
    )!;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(panel.hidden).toBe(true);

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(panel.hidden).toBe(false);
    expect(panel.textContent).toContain(`Goal${OBJECTIVE}`);
    expect(panel.textContent).toContain("Goal check note (from the checker)");
    const note = screen.getByTestId("goal-status-note");
    expect(note.textContent).toBe("The summary has only two lines.");
    expect(note.getAttribute("dir")).toBe("auto");
    expect(toggle.textContent).toBe("Hide details");
  });

  it("labels the note as the checker's own words in zh-CN", () => {
    render(bar({ goal: null, outcome: makeOutcome() }, "zh-CN"));
    const toggle = screen.getByRole("button", { name: "详情" });
    fireEvent.click(toggle);
    expect(screen.getByTestId("goal-status-details").textContent).toContain(
      "目标检查说明（评估器原文）The summary has three lines.",
    );
    expect(toggle.textContent).toBe("收起详情");
  });

  it("shows no checker note for a paused goal", () => {
    // A skipped clear leaves the earlier unmet verdict in last_evaluation.
    render(
      bar({
        goal: makeGoal({
          continuation_count: 2,
          last_evaluation: {
            satisfied: false,
            blocker: "goal_not_met_yet",
            reason: "Totals missing.",
          },
        }),
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));
    const panel = screen.getByTestId("goal-status-details");
    expect(panel.textContent).toContain(OBJECTIVE);
    expect(panel.textContent).not.toContain("Totals missing.");
    expect(screen.queryByTestId("goal-status-note")).toBeNull();
  });

  it("starts each new state, or another goal, with Details collapsed", () => {
    const limit = stoodDown("max_continuations_reached", {
      continuation_count: 8,
    });
    const { rerender } = render(bar({ goal: limit }));
    const toggle = () => screen.getByRole("button", { name: /details/i });
    const expanded = () => toggle().getAttribute("aria-expanded");
    fireEvent.click(toggle());
    expect(expanded()).toBe("true");

    // A language switch keeps it open; a counter-free re-render too.
    rerender(bar({ goal: { ...limit } }, "zh-CN"));
    expect(screen.getByRole("button", { name: "收起详情" })).toBeTruthy();
    rerender(bar({ goal: limit }));

    rerender(
      bar({ goal: makeGoal({ continuation_count: 8 }), isRunning: true }),
    );
    rerender(bar({ goal: null, outcome: makeOutcome() }));
    expect(expanded()).toBe("false");
    expect(screen.getByTestId("goal-status-details").hidden).toBe(true);
    expect(screen.queryByTestId("goal-status-note")).toBeNull();

    fireEvent.click(toggle());
    rerender(bar({ goal: limit }));
    fireEvent.click(toggle());
    expect(expanded()).toBe("true");
    // The same state of another goal, as after a thread switch.
    rerender(
      bar({
        goal: stoodDown("max_continuations_reached", {
          created_at: "2026-10-08T00:00:00Z",
          continuation_count: 8,
        }),
      }),
    );
    expect(expanded()).toBe("false");
  });

  it.each([
    ["a check failure", stoodDown("thread_changed_after_evaluation"), false],
    [
      "a host-written reason",
      stoodDown(
        "blocked:needs_user_input",
        {},
        "The turn ended on a question to the user that has not been answered.",
      ),
      true,
    ],
  ])("shows no checker note for %s", (_case, goal, hasOpenHumanInputCard) => {
    render(bar({ goal, hasOpenHumanInputCard }, "zh-CN"));
    fireEvent.click(screen.getByRole("button", { name: /详情/ }));
    const panel = screen.getByTestId("goal-status-details");
    expect(panel.textContent).toContain(OBJECTIVE);
    expect(panel.textContent).not.toContain("目标检查说明");
    expect(panel.textContent).not.toContain(goal.last_evaluation!.reason);
    expect(screen.queryByTestId("goal-status-note")).toBeNull();
  });

  it("keeps an unknown code out of the default view and shows it in Details", () => {
    render(bar({ goal: stoodDown("blocked:new_reason") }));
    expect(section().textContent).not.toContain("new_reason");
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));
    expect(screen.getByTestId("goal-status-details").textContent).toContain(
      "blocked:new_reason",
    );
  });

  it("describes the assumption badge and repeats it in Details", () => {
    render(
      bar({
        goal: null,
        outcome: makeOutcome({ relied_on_assumption: true }),
      }),
    );
    const badge = screen.getByTestId("goal-status-assumption");
    expect(badge.tabIndex).toBe(0);
    const description = document.getElementById(
      badge.getAttribute("aria-describedby")!,
    );
    expect(description?.textContent).toBe(
      enUS.inputBox.goalBar.assumptionTooltip,
    );
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));
    expect(screen.getByTestId("goal-status-details").textContent).toContain(
      "The agent filled in something the goal didn't specify",
    );
  });

  it("has no Details for a goal that is only set or running", () => {
    render(bar({ goal: makeGoal(), isRunning: true }));
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("GoalStatus a11y", () => {
  it("is a labelled region with the met icon state in text", () => {
    render(bar({ goal: null, outcome: makeOutcome() }, "zh-CN"));
    expect(screen.getByRole("region", { name: "目标状态" })).toBe(section());
    expect(section().getAttribute("data-goal-state")).toBe("met");
    cleanup();
    render(bar({ goal: makeGoal() }));
    expect(screen.getByRole("region", { name: "Goal status" })).toBe(section());
  });

  it("announces a state change once, not each streamed counter", () => {
    const running = (count: number) =>
      bar({
        goal: makeGoal({ continuation_count: count }),
        isRunning: true,
      });
    const { rerender } = render(running(0));
    expect(liveRegion().textContent).toBe("");

    rerender(running(1));
    expect(liveRegion().textContent).toBe("Goal: Continuing 1/8");
    rerender(running(2));
    expect(screen.getByText("Continuing 2/8")).toBeTruthy();
    expect(liveRegion().textContent).toBe("Goal: Continuing 1/8");

    rerender(
      bar({ goal: null, outcome: makeOutcome({ continuation_count: 2 }) }),
    );
    expect(liveRegion().textContent).toBe(`Goal met: ${OBJECTIVE}`);
  });

  it("announces the stop reason with its next step", () => {
    const { rerender } = render(bar({ goal: makeGoal(), isRunning: true }));
    rerender(bar({ goal: stoodDown("token_capped") }));
    expect(liveRegion().textContent).toBe(
      "Stopped: Token budget reached. Send a message to continue; a new run starts with a fresh budget.",
    );
  });

  it("re-reads the live text in the new language", () => {
    const limit = stoodDown("max_continuations_reached", {
      continuation_count: 8,
    });
    const { rerender } = render(bar({ goal: limit }));
    expect(liveRegion().textContent).toContain(
      "Stopped: Continuation limit reached · 8/8.",
    );
    rerender(bar({ goal: limit }, "zh-CN"));
    expect(liveRegion().textContent).toBe(
      "已停止：已达到自动续跑上限 8/8，不会再自动续跑。回复即可继续；或用 /goal <完成条件> 重新设置目标，次数从零开始（同时会开始一次新的运行）。",
    );
  });

  it("announces the same state of another goal or record", () => {
    const { rerender } = render(
      bar({
        goal: stoodDown("max_continuations_reached", { continuation_count: 8 }),
      }),
    );
    rerender(
      bar({
        goal: stoodDown("max_continuations_reached", {
          objective: "Translate it",
          created_at: "2026-10-08T00:00:00Z",
          continuation_count: 3,
          max_continuations: 3,
        }),
      }),
    );
    expect(liveRegion().textContent).toContain(
      "Continuation limit reached · 3/3.",
    );

    rerender(bar({ goal: null, outcome: makeOutcome() }));
    expect(liveRegion().textContent).toBe(`Goal met: ${OBJECTIVE}`);
    rerender(
      bar({
        goal: null,
        outcome: makeOutcome({
          objective: "Translate it",
          goal_created_at: "2026-10-08T00:00:00Z",
          achieved_at: "2026-10-08T00:09:00Z",
        }),
      }),
    );
    expect(liveRegion().textContent).toBe("Goal met: Translate it");
  });
});

describe("GoalStatus visuals", () => {
  function chipClass() {
    return screen.getByTestId("goal-status-chip").className;
  }

  it.each([
    [
      "stopped",
      stoodDown("max_continuations_reached", { continuation_count: 8 }),
      "text-amber-700",
    ],
    [
      "stopped (unknown code)",
      stoodDown("blocked:new_reason"),
      "text-amber-700",
    ],
    ["waiting for you", stoodDown("blocked:needs_user_input"), "text-primary"],
    ["waiting", stoodDown("blocked:external_wait"), "text-muted-foreground"],
    ["unchecked", stoodDown("evaluator_failed"), "text-muted-foreground"],
  ])("tones the %s chip", (_name, goal, tone) => {
    render(bar({ goal }));
    const classes = chipClass().split(" ");
    expect(classes).toContain(tone);
    for (const other of [
      "text-amber-700",
      "text-primary",
      "text-muted-foreground",
    ]) {
      if (other !== tone) {
        expect(classes).not.toContain(other);
      }
    }
  });

  it.each([
    [
      "auto-continue off",
      stoodDown("max_continuations_reached", { max_continuations: 0 }),
    ],
    ["no progress", stoodDown("no_progress_detected")],
    ["missing evidence", stoodDown("blocked:missing_evidence")],
  ])(
    "marks the %s stop with a stop icon, not the pause icon",
    (_name, goal) => {
      render(bar({ goal }));
      const chip = screen.getByTestId("goal-status-chip");
      expect(chip.querySelector(".lucide-circle-stop")).not.toBeNull();
      expect(chip.querySelector(".lucide-circle-pause")).toBeNull();
    },
  );

  it("tones the paused chip muted", () => {
    render(
      bar({
        goal: makeGoal({
          continuation_count: 2,
          last_evaluation: {
            satisfied: false,
            blocker: "goal_not_met_yet",
            reason: "Two lines so far.",
          },
        }),
      }),
    );
    expect(chipClass().split(" ")).toContain("text-muted-foreground");
    expect(chipClass()).not.toContain("amber");
  });

  it("replaces the target icon with a green check when the goal is met", () => {
    const { rerender } = render(bar({ goal: makeGoal() }));
    const leading = () => section().firstElementChild!.firstElementChild!;
    expect(leading().getAttribute("aria-hidden")).toBe("true");
    expect(leading().querySelector(".lucide-target")).not.toBeNull();
    expect(leading().className).toContain("text-primary");

    rerender(bar({ goal: null, outcome: makeOutcome() }));
    expect(leading().getAttribute("aria-hidden")).toBe("true");
    expect(leading().querySelector(".lucide-target")).toBeNull();
    expect(leading().querySelector(".lucide-circle-check")).not.toBeNull();
    expect(leading().className).toContain("text-emerald-600");
    // The color change follows the reduced-motion setting.
    expect(leading().className.split(" ")).toContain(
      "motion-safe:transition-colors",
    );
  });

  it("hides every icon from screen readers and spins only with motion allowed", () => {
    const { rerender } = render(bar({ goal: makeGoal(), isRunning: true }));
    const spinner = section().querySelector(".lucide-loader-circle")!;
    const spinnerClasses = spinner.getAttribute("class")!.split(" ");
    expect(spinnerClasses).toContain("motion-safe:animate-spin");
    expect(spinnerClasses).not.toContain("animate-spin");

    for (const goal of [
      makeGoal({ continuation_count: 2 }),
      stoodDown("max_continuations_reached", { continuation_count: 8 }),
    ]) {
      rerender(bar({ goal, isRunning: goal.continuation_count === 2 }));
      const icons = section().querySelectorAll("svg");
      expect(icons.length).toBeGreaterThan(0);
      for (const icon of icons) {
        expect(icon.closest('[aria-hidden="true"]')).not.toBeNull();
      }
    }
  });
});
