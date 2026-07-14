import { describe, expect, it } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { SubtaskCard } from "@/components/workspace/messages/subtask-card";
import { I18nContext } from "@/core/i18n/context";
import { SubtaskContext } from "@/core/tasks/context";
import type { Subtask } from "@/core/tasks/types";

function baseTask(overrides: Partial<Subtask> = {}): Subtask {
  return {
    id: "task-1",
    status: "in_progress",
    subagent_type: "researcher",
    description: "Research the topic",
    prompt: "Find sources",
    ...overrides,
  };
}

describe("SubtaskCard", () => {
  it("renders a failed fallback snapshot ahead of stale in-progress context state", () => {
    const html = renderCard({
      contextTask: baseTask({ status: "in_progress" }),
      fallbackTask: baseTask({
        status: "failed",
        error: "Subtask failed",
      }),
    });

    expect(html).toContain("Subtask failed");
    expect(html).not.toContain("Running subtask");
  });

  it("renders a completed fallback snapshot ahead of stale in-progress context state", () => {
    const html = renderCard({
      contextTask: baseTask({
        status: "in_progress",
        steps: [
          {
            kind: "tool",
            message_index: 1,
            text: "Collected sources",
            truncated: false,
          },
        ],
      }),
      fallbackTask: baseTask({
        status: "completed",
        result: "done",
      }),
    });

    expect(html).toContain("Subtask completed");
    expect(html).not.toContain("Running subtask");
  });
});

function renderCard({
  contextTask,
  fallbackTask,
}: {
  contextTask?: Subtask;
  fallbackTask?: Subtask;
}) {
  const tasks = contextTask ? { [contextTask.id]: contextTask } : {};
  const queryClient = new QueryClient();

  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      {
        client: queryClient,
      },
      createElement(
        I18nContext.Provider,
        {
          value: {
            locale: "en-US",
            setLocale: () => undefined,
          },
        },
        createElement(
          SubtaskContext.Provider,
          {
            value: {
              tasks,
              tasksRef: { current: tasks },
              setTasks: () => undefined,
            },
          },
          createElement(SubtaskCard, {
            taskId: fallbackTask?.id ?? contextTask?.id ?? "task-1",
            isLoading: false,
            fallbackTask,
          }),
        ),
      ),
    ),
  );
}
