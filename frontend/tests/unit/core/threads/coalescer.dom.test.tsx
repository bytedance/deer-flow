import type { Message } from "@langchain/langgraph-sdk";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

import { useCoalescedStreamMessages } from "@/core/threads/hooks";

const INTERVAL = 80;
const messages = (content: string): Message[] => [
  { type: "ai", id: "tail", content },
];
let now = 0;

function advance(ms: number) {
  act(() => {
    now += ms;
    rs.advanceTimersByTime(ms);
  });
}

beforeEach(() => {
  now = 0;
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  rs.spyOn(performance, "now").mockImplementation(() => now);
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.useRealTimers();
});

describe("useCoalescedStreamMessages", () => {
  test.each([
    { label: "empty", stableMessages: [] },
    { label: "unchanged", stableMessages: messages("unchanged") },
  ])(
    "accepts SDK getter arrays without a publication loop ($label)",
    ({ stableMessages }) => {
      let renders = 0;
      const hook = renderHook(() => {
        // A synchronous effect loop cannot be stopped by a test timeout. This
        // generous guard bounds the failure if the equality check regresses.
        if (++renders > 60) throw new Error("Coalescer render budget exceeded");
        // Cross a leading edge on every render, including effect-driven ones.
        now += INTERVAL;
        return useCoalescedStreamMessages([...stableMessages], true, INTERVAL);
      });

      for (let index = 0; index < 10; index++) hook.rerender();

      expect(hook.result.current).toEqual(stableMessages);
    },
  );

  test("publishes the latest chunk on the trailing edge without starvation", () => {
    const first = messages("first");
    const hook = renderHook(
      ({ input }) => useCoalescedStreamMessages(input, true, INTERVAL),
      { initialProps: { input: first } },
    );
    expect(hook.result.current).toBe(first);

    let latest = first;
    for (let index = 1; index <= 7; index++) {
      advance(10);
      latest = messages(`chunk ${index}`);
      hook.rerender({ input: latest });
      expect(hook.result.current).toBe(first);
      expect(rs.getTimerCount()).toBe(1);
    }

    advance(10);
    expect(hook.result.current).toBe(latest);
    expect(rs.getTimerCount()).toBe(0);

    advance(10);
    const next = messages("next interval");
    hook.rerender({ input: next });
    expect(hook.result.current).toBe(latest);
    advance(69);
    expect(hook.result.current).toBe(latest);
    advance(1);
    expect(hook.result.current).toBe(next);
  });

  test("returns final live messages on stop and starts the next run without an old snapshot", () => {
    const first = messages("first run");
    const observed: Message[][] = [];
    const hook = renderHook(
      ({ input, loading }) => {
        const output = useCoalescedStreamMessages(input, loading, INTERVAL);
        // Capture the render before passive effects: result.current alone can
        // hide an old snapshot that an effect immediately replaces.
        observed.push(output);
        return output;
      },
      { initialProps: { input: first, loading: true } },
    );
    advance(10);
    const pending = messages("pending");
    hook.rerender({ input: pending, loading: true });
    expect(hook.result.current).toBe(first);
    expect(rs.getTimerCount()).toBe(1);

    const final = messages("final");
    observed.length = 0;
    hook.rerender({ input: final, loading: false });
    expect(observed[0]).toBe(final);
    expect(hook.result.current).toBe(final);
    expect(rs.getTimerCount()).toBe(0);

    const idle = messages("idle update");
    hook.rerender({ input: idle, loading: false });
    expect(hook.result.current).toBe(idle);

    const next = messages("new run");
    observed.length = 0;
    hook.rerender({ input: next, loading: true });
    expect(observed[0]).toBe(next);
    expect(hook.result.current).toBe(next);
    expect(rs.getTimerCount()).toBe(0);

    advance(1);
    const chunk = messages("new run chunk");
    hook.rerender({ input: chunk, loading: true });
    expect(hook.result.current).toBe(next);
    advance(79);
    expect(hook.result.current).toBe(chunk);
  });

  test("disarms an overdue trailing timer when a new chunk takes the leading edge", () => {
    const first = messages("first");
    const hook = renderHook(
      ({ input }) => useCoalescedStreamMessages(input, true, INTERVAL),
      { initialProps: { input: first } },
    );
    advance(10);
    hook.rerender({ input: messages("pending") });
    expect(rs.getTimerCount()).toBe(1);

    // Hold timer execution while the monotonic clock advances, like a blocked
    // main thread delivering another chunk before its overdue timer callback.
    now = 100;
    const leading = messages("leading");
    hook.rerender({ input: leading });
    expect(hook.result.current).toBe(leading);
    expect(rs.getTimerCount()).toBe(0);
    advance(10);
    const next = messages("after leading");
    hook.rerender({ input: next });
    advance(69);
    expect(hook.result.current).toBe(leading);
    advance(1);
    expect(hook.result.current).toBe(next);
  });

  test("clears the pending trailing timer on unmount", () => {
    const hook = renderHook(
      ({ input }) => useCoalescedStreamMessages(input, true, INTERVAL),
      { initialProps: { input: messages("first") } },
    );
    advance(10);
    hook.rerender({ input: messages("pending") });
    expect(rs.getTimerCount()).toBe(1);

    hook.unmount();

    expect(rs.getTimerCount()).toBe(0);
    advance(INTERVAL);
    expect(rs.getTimerCount()).toBe(0);
  });
});
