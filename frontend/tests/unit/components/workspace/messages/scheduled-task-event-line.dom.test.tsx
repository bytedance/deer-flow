import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { ScheduledTaskEventLine } from "@/components/workspace/messages/scheduled-task-event-line";
import type { Locale } from "@/core/i18n";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { ScheduledTaskEvent } from "@/core/scheduled-tasks/events";

import { expectNoRawIdentifiers } from "../../../helpers/readable";

rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(cleanup);

const TASK_ID = "task-2b559ac2af344c3f9e55b90391f7fb1a";
const RUN_THREAD_ID = "83d5133d-f8aa-4095-9bba-2aca03f8f61c";
const EVENT_ID = "evt-5f0b4cfd0e1e4a2f9e7b3a1c2d4e6f80";

function eventOf(overrides: Partial<ScheduledTaskEvent>): ScheduledTaskEvent {
  return {
    id: EVENT_ID,
    task_id: TASK_ID,
    event: "task_stopped",
    reason_code: "agent_stop",
    task_title: "Release checklist watcher",
    stop_condition: null,
    run_thread_id: RUN_THREAD_ID,
    run_number: 2,
    run_status: "success",
    max_runs: null,
    end_at: null,
    schedule_type: "cron",
    after_run_id: "41e5fae0-0ffd-4af7-809b-c71d6dd2bb39",
    created_at: "2026-10-07T01:01:00+00:00",
    ...overrides,
  };
}

function renderLine(
  locale: Locale,
  event: ScheduledTaskEvent,
  agentName?: string,
) {
  return render(
    <I18nContext.Provider
      value={{
        locale,
        setLocale: () => undefined,
        t: locale === "zh-CN" ? zhCN : enUS,
      }}
    >
      <ScheduledTaskEventLine event={event} agentName={agentName} />
    </I18nContext.Provider>,
  );
}

const line = () => screen.getByTestId("scheduled-task-event-line");
const text = () => screen.getByTestId("scheduled-task-event-text");
const action = () => screen.getByTestId("scheduled-task-event-action");

const RUN_HREF = `/workspace/chats/${RUN_THREAD_ID}`;
const TASK_HREF = `/workspace/scheduled-tasks?task_id=${TASK_ID}`;

type Case = {
  name: string;
  event: Partial<ScheduledTaskEvent>;
  kind: string;
  icon: string;
  en: { text: string; action: string };
  zh: { text: string; action: string };
  href: string;
};

const CASES: Case[] = [
  {
    name: "paused by the agent, with its stop condition",
    event: { stop_condition: "every item on the checklist is checked" },
    kind: "stopped",
    icon: "lucide-circle-pause",
    en: {
      text: "Release checklist watcher was paused by the agent. Stop condition met: every item on the checklist is checked",
      action: "See that run",
    },
    zh: {
      text: "Release checklist watcher 已由智能体暂停。停止条件已满足：every item on the checklist is checked",
      action: "查看那次运行",
    },
    href: RUN_HREF,
  },
  {
    name: "paused by the agent, no condition recorded",
    event: {},
    kind: "stopped",
    icon: "lucide-circle-pause",
    en: {
      text: "Release checklist watcher was paused by the agent: its stop condition was met.",
      action: "See that run",
    },
    zh: {
      text: "Release checklist watcher 已由智能体暂停：停止条件已满足。",
      action: "查看那次运行",
    },
    href: RUN_HREF,
  },
  {
    name: "paused by the agent after a failed run",
    event: { run_status: "failed" },
    kind: "stopped",
    icon: "lucide-circle-pause",
    en: {
      text: "Release checklist watcher was paused by the agent: its stop condition was met. The last run failed.",
      action: "See that run",
    },
    zh: {
      text: "Release checklist watcher 已由智能体暂停：停止条件已满足。最后一次运行出错了。",
      action: "查看那次运行",
    },
    href: RUN_HREF,
  },
  {
    // The condition is the user's own words, without a final stop.
    name: "paused by the agent with its stop condition, after a failed run",
    event: {
      stop_condition: "清单上的所有项都已勾选",
      run_status: "failed",
    },
    kind: "stopped",
    icon: "lucide-circle-pause",
    en: {
      text: "Release checklist watcher was paused by the agent. Stop condition met: 清单上的所有项都已勾选. The last run failed.",
      action: "See that run",
    },
    zh: {
      text: "Release checklist watcher 已由智能体暂停。停止条件已满足：清单上的所有项都已勾选。最后一次运行出错了。",
      action: "查看那次运行",
    },
    href: RUN_HREF,
  },
  {
    name: "paused by the agent on a skipped occurrence (no run chat)",
    event: { run_thread_id: null, run_status: "skipped" },
    kind: "stopped",
    icon: "lucide-circle-pause",
    en: {
      text: "Release checklist watcher was paused by the agent: its stop condition was met.",
      action: "Open task",
    },
    zh: {
      text: "Release checklist watcher 已由智能体暂停：停止条件已满足。",
      action: "查看任务",
    },
    href: TASK_HREF,
  },
  {
    name: "auto-paused",
    event: {
      event: "task_paused",
      reason_code: "consecutive_unmet",
      run_status: "unmet",
    },
    kind: "autoPaused",
    icon: "lucide-circle-pause",
    en: {
      text: "Release checklist watcher was paused automatically: 3 runs in a row missed the goal.",
      action: "Open task",
    },
    zh: {
      text: "Release checklist watcher 已自动暂停：连续 3 次未达成目标。",
      action: "查看任务",
    },
    href: TASK_HREF,
  },
  {
    name: "finished: all runs done",
    event: { event: "task_finished", reason_code: "max_runs", max_runs: 5 },
    kind: "finished",
    icon: "lucide-circle-check",
    en: {
      text: "Release checklist watcher finished: all 5 runs are done.",
      action: "Open task",
    },
    zh: {
      text: "Release checklist watcher 已结束：5 次运行已全部完成。",
      action: "查看任务",
    },
    href: TASK_HREF,
  },
  {
    name: "finished: all runs done, the last one missed the goal",
    event: {
      event: "task_finished",
      reason_code: "max_runs",
      max_runs: 5,
      run_status: "unmet",
    },
    kind: "finished",
    icon: "lucide-circle-check",
    en: {
      text: "Release checklist watcher finished: all 5 runs are done. The last run didn't meet the goal.",
      action: "Open task",
    },
    zh: {
      text: "Release checklist watcher 已结束：5 次运行已全部完成。最后一次运行未达成目标。",
      action: "查看任务",
    },
    href: TASK_HREF,
  },
  {
    name: "finished: end time passed",
    event: {
      event: "task_finished",
      reason_code: "end_at",
      end_at: "2026-10-07T00:00:00+00:00",
      run_thread_id: null,
      run_status: null,
    },
    kind: "finished",
    icon: "lucide-circle-check",
    en: {
      text: "Release checklist watcher finished: its end time has passed.",
      action: "Open task",
    },
    zh: {
      text: "Release checklist watcher 已结束：已过结束时间。",
      action: "查看任务",
    },
    href: TASK_HREF,
  },
  {
    name: "a one-time task ran",
    event: {
      event: "task_finished",
      reason_code: "once_done",
      schedule_type: "once",
    },
    kind: "onceDone",
    icon: "lucide-circle-check",
    en: { text: "Release checklist watcher has run.", action: "See that run" },
    zh: {
      text: "Release checklist watcher 已运行。",
      action: "查看那次运行",
    },
    href: RUN_HREF,
  },
  {
    name: "a one-time task did not finish (no suffix: the line says it)",
    event: {
      event: "task_finished",
      reason_code: "once_failed",
      schedule_type: "once",
      run_status: "failed",
    },
    kind: "onceFailed",
    icon: "lucide-circle-x",
    en: {
      text: "Release checklist watcher didn't finish.",
      action: "See that run",
    },
    zh: {
      text: "Release checklist watcher 没有成功完成。",
      action: "查看那次运行",
    },
    href: RUN_HREF,
  },
];

describe("ScheduledTaskEventLine", () => {
  for (const item of CASES) {
    for (const locale of ["en-US", "zh-CN"] as const) {
      test(`${item.name} (${locale})`, () => {
        const copy = locale === "zh-CN" ? item.zh : item.en;
        renderLine(locale, eventOf(item.event));

        const note = screen.getByRole("note", {
          name: locale === "zh-CN" ? "定时任务通知" : "Scheduled task update",
        });
        expect(note).toBe(line());
        expect(note.getAttribute("data-task-id")).toBe(TASK_ID);
        expect(note.getAttribute("data-event-id")).toBe(EVENT_ID);
        expect(note.getAttribute("data-event-kind")).toBe(item.kind);

        // Main sentence and suffix; the time follows in its own element.
        const time = text().querySelector("time");
        expect(time).not.toBeNull();
        expect(time!.getAttribute("datetime")).toBe(
          "2026-10-07T01:01:00+00:00",
        );
        // A real space before the time keeps the accessible text apart.
        expect(text().textContent).toBe(
          `${copy.text} ${time!.textContent ?? ""}`,
        );
        expect(text().querySelector("strong")?.textContent).toBe(
          "Release checklist watcher",
        );

        expect(action().textContent).toBe(copy.action);
        expect(action().getAttribute("href")).toBe(item.href);

        const icon = note.querySelector("svg");
        expect(icon?.getAttribute("class")).toContain(item.icon);
        expect(icon?.getAttribute("aria-hidden")).toBe("true");

        expectNoRawIdentifiers(note);
        if (locale === "zh-CN") {
          expect(note.textContent).toMatch(/[一-鿿]/);
        }
      });
    }
  }

  test("a Chinese title stays bold and the copy reads in Chinese", () => {
    renderLine(
      "zh-CN",
      eventOf({
        task_title: "发布清单未完成项监控",
        stop_condition: "清单上的所有项都已勾选",
      }),
    );
    expect(text().querySelector("strong")?.textContent).toBe(
      "发布清单未完成项监控",
    );
    // No ASCII space between a Chinese title and the predicate.
    expect(text().textContent).toContain(
      "发布清单未完成项监控已由智能体暂停。停止条件已满足：清单上的所有项都已勾选",
    );
    expect(text().textContent).not.toMatch(/paused|Stop condition/);
  });

  test("the stop condition is clamped to one line with the full text in its tooltip", () => {
    const condition =
      "every item on the release checklist is checked, the release notes are published and the Docker image is pushed to the registry";
    renderLine("en-US", eventOf({ stop_condition: condition }));
    const clamp = screen.getByTestId("scheduled-task-event-condition");
    expect(clamp.textContent).toBe(condition);
    expect(clamp.getAttribute("title")).toBe(condition);
    expect(clamp.className).toContain("truncate");
    expect(clamp.className).toContain("max-w-full");
  });

  test("the action link is described by the line, so several links read apart", () => {
    renderLine("en-US", eventOf({}));
    const describedBy = action().getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)).toBe(text());
  });

  test("a missing title reads as Untitled task, never the task id", () => {
    renderLine("en-US", eventOf({ task_title: "  " }));
    expect(text().querySelector("strong")?.textContent).toBe("Untitled task");
    renderLine("zh-CN", eventOf({ task_title: null }));
    expect(
      screen.getAllByTestId("scheduled-task-event-text")[1]!.textContent,
    ).toContain("未命名任务");
    expect(document.body.textContent).not.toContain(TASK_ID);
  });

  test("See that run opens the run chat on the custom agent of this chat", () => {
    renderLine("en-US", eventOf({}), "release-bot");
    expect(action().getAttribute("href")).toBe(
      `/workspace/agents/release-bot/chats/${RUN_THREAD_ID}`,
    );
  });

  test("Open task is not rerouted by the chat's agent", () => {
    renderLine(
      "en-US",
      eventOf({ event: "task_paused", reason_code: "consecutive_unmet" }),
      "release-bot",
    );
    expect(action().getAttribute("href")).toBe(TASK_HREF);
  });

  test("an event this client does not know renders nothing", () => {
    renderLine("en-US", eventOf({ event: "task_archived" }));
    expect(screen.queryByTestId("scheduled-task-event-line")).toBeNull();
  });
});
