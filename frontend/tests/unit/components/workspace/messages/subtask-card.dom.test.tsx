import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useEffect, useMemo, useState } from "react";

import { SubtaskCard } from "@/components/workspace/messages/subtask-card";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { fetchSubtaskSteps } from "@/core/tasks/api";
import {
  SubtasksProvider,
  useSubtaskContext,
  useUpdateSubtask,
} from "@/core/tasks/context";
import { collectRenderedSubtasks } from "@/core/tasks/subtask-render";
import type { Subtask } from "@/core/tasks/types";

rs.mock("@/core/tasks/api", () => ({ fetchSubtaskSteps: rs.fn() }));

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function setup(history = false) {
  let completeArguments: () => void;
  let publish: ReturnType<typeof useUpdateSubtask>;
  let readTask: () => Subtask;
  function Messages() {
    const [args, setArgs] = useState({ description: "Res", prompt: "" });
    const update = useUpdateSubtask();
    const { tasksRef } = useSubtaskContext();
    const rendered = useMemo(
      () =>
        collectRenderedSubtasks(
          [
            {
              id: "group-1",
              type: "assistant:subagent",
              messages: [
                {
                  type: "ai",
                  id: "message-1",
                  content: "",
                  tool_calls: [
                    {
                      id: "task-1",
                      name: "task",
                      args: { subagent_type: "researcher", ...args },
                    },
                  ],
                } as Message,
              ],
            },
          ],
          () => true,
          "Subtask failed",
          "Subtask",
        ),
      [args],
    );
    useEffect(() => {
      for (const task of rendered.updates) update(task);
    }, [rendered, update]);
    useEffect(() => {
      publish = update;
      readTask = () => tasksRef.current["task-1"]!;
      completeArguments = () => {
        update({ id: "task-1", modelName: "test-model" });
        setArgs({
          description: "Research the topic",
          prompt: "Find and compare reliable sources",
        });
      };
    });
    return (
      <SubtaskCard
        taskId="task-1"
        threadId={history ? "thread-1" : undefined}
        runId={history ? "run-1" : undefined}
        isLoading
        fallbackTask={rendered.tasks.get("task-1")!}
      />
    );
  }
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["models"], {
    models: [],
    token_usage: { enabled: true },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        <SubtasksProvider>
          <Messages />
        </SubtasksProvider>
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
  return {
    ...view,
    complete: () => completeArguments!(),
    publish: (task: Partial<Subtask> & { id: string }) => publish!(task),
    read: () => readTask!(),
  };
}

describe("SubtaskCard message synchronization", () => {
  it("merges a delayed history backfill with live steps after argument synchronization", async () => {
    let finishBackfill!: (steps: NonNullable<Subtask["steps"]>) => void;
    rs.mocked(fetchSubtaskSteps).mockImplementation(
      () =>
        new Promise((resolve) => {
          finishBackfill = resolve;
        }),
    );
    const view = setup(true);
    fireEvent.click(screen.getByRole("button"));
    expect(fetchSubtaskSteps).toHaveBeenCalledWith(
      "thread-1",
      "run-1",
      "task-1",
    );
    const live = {
      kind: "tool" as const,
      message_index: 2,
      text: "live",
      tool_name: "web_search",
    };
    const historical = {
      kind: "tool" as const,
      message_index: 1,
      text: "history",
      tool_name: "read_file",
    };
    await act(async () => view.publish({ id: "task-1", steps: [live] }));
    await act(async () => view.complete());
    await act(async () => finishBackfill([historical]));
    expect(view.read().steps).toEqual([historical, live]);
    expect(view.container.textContent).toContain("read_file");
    expect(view.container.textContent).toContain("web_search");
    expect(view.container.textContent).toContain(
      "Find and compare reliable sources",
    );
  });

  it("updates the folded title when final arguments and task_started arrive together", async () => {
    const view = setup();
    expect(screen.getByRole("button").textContent).toContain("Res");
    await act(async () => view.complete());
    expect(view.read().description).toBe("Research the topic");
    expect(screen.getByRole("button").textContent).toContain(
      "Research the topic",
    );
    expect(view.container.textContent).toContain("test-model");
  });

  it("updates an already-expanded prompt without another event or click", async () => {
    const view = setup();
    fireEvent.click(screen.getByRole("button"));
    await act(async () => view.complete());
    expect(view.read().prompt).toBe("Find and compare reliable sources");
    expect(view.container.textContent).toContain(
      "Find and compare reliable sources",
    );
    expect(screen.getByRole("button").textContent).toContain(
      "Research the topic",
    );
  });

  it("preserves live steps, usage and terminal state while completing arguments", async () => {
    const view = setup();
    const step = {
      kind: "tool" as const,
      message_index: 1,
      text: "Collected sources",
      tool_name: "web_search",
      truncated: false,
    };
    const usage = { inputTokens: 800, outputTokens: 200, totalTokens: 1000 };
    await act(async () => view.publish({ id: "task-1", steps: [step], usage }));
    await act(async () =>
      view.publish({
        id: "task-1",
        status: "completed",
        result: "Finished research",
      }),
    );
    await act(async () => view.complete());
    expect(screen.getByRole("button").textContent).toContain(
      "Research the topic",
    );
    expect(view.container.textContent).toContain("Subtask completed");
    expect(view.container.textContent).toContain("1,000 Tokens");
    expect(view.container.textContent).not.toContain("Running subtask");
    fireEvent.click(screen.getByRole("button"));
    expect(view.container.textContent).toContain("web_search");
    expect(view.container.textContent).toContain("Finished research");
    expect(view.read()).toMatchObject({
      status: "completed",
      steps: [step],
      usage,
    });
  });
});
