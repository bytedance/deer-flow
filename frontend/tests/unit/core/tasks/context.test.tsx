// @vitest-environment jsdom
import type { AIMessage } from "@langchain/langgraph-sdk";
import { act, render, renderHook, screen } from "@testing-library/react";
import * as React from "react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SubtasksProvider,
  useLatestSubtaskMessage,
  useUpdateLatestMessage,
} from "@/core/tasks/context";

afterEach(() => {
  vi.restoreAllMocks();
});

function wrap({ children }: { children: React.ReactNode }) {
  return <SubtasksProvider>{children}</SubtasksProvider>;
}

describe("SubtasksProvider — latest message context", () => {
  it("returns undefined until the SSE handler registers a message", () => {
    const { result } = renderHook(() => useLatestSubtaskMessage("task-x"), {
      wrapper: wrap,
    });
    expect(result.current).toBeUndefined();
  });

  it("publishes the registered AIMessage to consumers", () => {
    const message = {
      id: "msg-1",
      type: "ai",
      content: "subagent thinking",
    } as unknown as AIMessage;

    const { result, rerender } = renderHook(
      () => ({
        update: useUpdateLatestMessage(),
        msg: useLatestSubtaskMessage("task-y"),
      }),
      { wrapper: wrap },
    );

    act(() => {
      result.current.update("task-y", message);
    });
    rerender();

    expect(result.current.msg).toBe(message);
  });

  it("keys messages by task id without bleeding across tasks", () => {
    const a = { id: "a", type: "ai", content: "a" } as unknown as AIMessage;
    const b = { id: "b", type: "ai", content: "b" } as unknown as AIMessage;

    const { result, rerender } = renderHook(
      () => ({
        update: useUpdateLatestMessage(),
        msgA: useLatestSubtaskMessage("task-a"),
        msgB: useLatestSubtaskMessage("task-b"),
      }),
      { wrapper: wrap },
    );

    act(() => {
      result.current.update("task-a", a);
      result.current.update("task-b", b);
    });
    rerender();

    expect(result.current.msgA).toBe(a);
    expect(result.current.msgB).toBe(b);
  });

  it("StrictMode double-render does not log 'Cannot update a component while rendering'", () => {
    // Regression test for #3147: the old `useUpdateSubtask` mutated
    // context state directly during render, which React Strict Mode's
    // double-render surfaces as a console.error. The new API only
    // exposes write paths that are intended to fire outside render
    // (effect / event handler), so there is no legitimate way to
    // trigger that warning from this provider any more.
    const errors: unknown[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
      errors.push(args);
    });

    function Reader() {
      const msg = useLatestSubtaskMessage("task-z");
      return <span>{msg ? "have-msg" : "no-msg"}</span>;
    }

    render(
      <StrictMode>
        <SubtasksProvider>
          <Reader />
        </SubtasksProvider>
      </StrictMode>,
    );

    expect(screen.getByText("no-msg")).toBeTruthy();

    const renderWarnings = errors.filter(
      (entry) =>
        Array.isArray(entry) &&
        entry.some(
          (msg) =>
            typeof msg === "string" &&
            /Cannot update a component .* while rendering a different component/i.test(
              msg,
            ),
        ),
    );
    expect(renderWarnings).toHaveLength(0);

    spy.mockRestore();
  });
});
