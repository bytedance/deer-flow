import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { ScheduledRunPrompt } from "@/components/workspace/messages/scheduled-run-prompt";
import { I18nProvider } from "@/core/i18n/context";
import { getMessageGroups } from "@/core/messages/utils";
import type { ScheduledOrigin } from "@/core/scheduled-tasks/types";

import { expectNoRawIdentifiers } from "../../../helpers/readable";
import { loadScheduledThread } from "../../../helpers/scheduled-fixtures";

rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(() => {
  cleanup();
  document.cookie = "locale=; max-age=0; path=/";
});

const NOTE = "Mention Sam by name";

/**
 * The recorded run thread's launch, with a standing note added so the
 * launched text carries both host-written parts (stop-rule paragraph and the
 * notes wrapper), as a real launch with notes does.
 */
function launch(name: "en-3-run-thread" | "zh-1-run-thread") {
  const { messages } = loadScheduledThread(name);
  const human = messages.find((message) => message.type === "human")!;
  const kwargs = human.additional_kwargs as {
    deerflow_scheduled_origin: ScheduledOrigin;
  };
  const withNote = {
    ...human,
    content: `${human.content as string}\n\n<standing_notes>\n- ${NOTE}\n</standing_notes>`,
    additional_kwargs: {
      deerflow_scheduled_origin: {
        ...kwargs.deerflow_scheduled_origin,
        standing_notes: [NOTE],
      },
    },
  };
  const group = getMessageGroups([withNote]).find(
    (item) => item.type === "human",
  );
  if (group?.type !== "human" || !group.scheduledOrigin) {
    throw new Error("fixture lost its scheduled origin");
  }
  return { text: withNote.content, origin: group.scheduledOrigin };
}

function renderPrompt(origin: ScheduledOrigin, locale: "en-US" | "zh-CN") {
  document.cookie = `locale=${locale}; path=/`;
  return render(
    <I18nProvider initialLocale={locale}>
      <ScheduledRunPrompt origin={origin} />
    </I18nProvider>,
  );
}

describe("ScheduledRunPrompt", () => {
  test("shows the run header and only the user-language parts of the launch", () => {
    const { text, origin } = launch("en-3-run-thread");
    expect(text).toContain("stop_scheduled_task");
    expect(text).toContain("<standing_notes>");
    renderPrompt(origin, "en-US");

    const block = screen.getByTestId("scheduled-run-prompt");
    expect(block.textContent).toContain("Scheduled run");
    expect(block.textContent).toContain(
      "Release checklist status watcher · run 2",
    );
    expect(
      screen.getByRole("link", { name: /Open task/ }).getAttribute("href"),
    ).toBe(`/workspace/scheduled-tasks?task_id=${origin.task_id}`);
    // Collapsed by default.
    expect(screen.queryByTestId("scheduled-run-instructions")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", {
        name: /Task instructions \(sent automatically\)/,
      }),
    );
    expect(screen.getByTestId("scheduled-run-instructions").textContent).toBe(
      origin.instructions,
    );
    expect(block.textContent).toContain(
      "Stops when: every item on the checklist is checked",
    );
    expect(block.textContent).toContain("Notes from chat");
    expect(block.textContent).toContain(NOTE);
    expect(block.textContent).not.toContain("Stop rule from the user");
    expect(block.textContent).not.toContain("stop_scheduled_task");
    expect(block.textContent).not.toContain("standing_notes");
    expectNoRawIdentifiers(block);
    expect(screen.queryByRole("button", { name: /edit/i })).toBeNull();
  });

  test("reads naturally in Chinese and labels a trial run", () => {
    const { origin } = launch("zh-1-run-thread");
    renderPrompt({ ...origin, trigger: "manual", run_number: null }, "zh-CN");
    const block = screen.getByTestId("scheduled-run-prompt");
    expect(block.textContent).toContain("试运行");
    expect(block.textContent).not.toContain("第");
    fireEvent.click(
      screen.getByRole("button", { name: /任务指令（自动发送）/ }),
    );
    expect(block.textContent).toContain("何时停止：清单上的所有项都已勾选");
    expect(block.textContent).toContain("对话中保存的备注");
    expect(block.textContent).not.toContain("Stop rule");
    expectNoRawIdentifiers(block);
  });

  test("numbers a Chinese scheduled run", () => {
    const { origin } = launch("zh-1-run-thread");
    renderPrompt(origin, "zh-CN");
    const block = screen.getByTestId("scheduled-run-prompt");
    expect(block.textContent).toContain("定时运行");
    expect(block.textContent).toContain("发布清单未完成项监控 · 第 2 次");
    expect(block.textContent).toContain("查看任务");
  });
});
