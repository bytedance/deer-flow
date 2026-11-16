import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

rs.mock("@/components/workspace/browser-view/api", () => ({
  browserStreamURL: (threadId: string) => `ws://example.test/${threadId}`,
}));

import { useBrowserStream } from "@/components/workspace/browser-view/use-browser-stream";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  binaryType = "";
  closeCalls = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((message: MessageEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send() {
    return undefined;
  }

  close() {
    this.closeCalls += 1;
    this.readyState = FakeWebSocket.CLOSED;
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  disconnect() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }
}

afterEach(() => {
  cleanup();
  rs.useRealTimers();
  rs.restoreAllMocks();
  rs.unstubAllGlobals();
  FakeWebSocket.instances = [];
});

describe("useBrowserStream", () => {
  // Regression coverage for bytedance/deer-flow#7296.
  test("times out a silent handshake and reconnects after the existing backoff", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result } = renderHook(() => useBrowserStream("thread-1", true));
    const first = FakeWebSocket.instances[0]!;

    act(() => {
      void rs.advanceTimersByTime(9_999);
    });
    expect(first.closeCalls).toBe(0);
    expect(result.current.status).toBe("connecting");

    act(() => {
      void rs.advanceTimersByTime(1);
    });
    expect(first.closeCalls).toBe(1);
    expect(result.current.status).toBe("closed");
    expect(FakeWebSocket.instances).toHaveLength(1);

    // close() deliberately emits no event: timeout recovery must not depend
    // on an eventual error/close event from the failed handshake.
    act(() => {
      void rs.advanceTimersByTime(799);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      void rs.advanceTimersByTime(1);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(result.current.status).toBe("connecting");
  });

  test("clears the handshake deadline after a successful open", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result } = renderHook(() => useBrowserStream("thread-1", true));
    const first = FakeWebSocket.instances[0]!;
    act(() => {
      void rs.advanceTimersByTime(9_999);
      first.open();
    });
    expect(rs.getTimerCount()).toBe(0);

    act(() => {
      void rs.advanceTimersByTime(300_000);
    });
    expect(result.current.status).toBe("open");
    expect(first.closeCalls).toBe(0);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  test("failure events share one reconnect and clear the failed handshake deadline", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result } = renderHook(() => useBrowserStream("thread-1", true));
    const first = FakeWebSocket.instances[0]!;
    act(() => {
      void rs.advanceTimersByTime(1_000);
      first.onerror?.();
      first.disconnect();
    });
    expect(rs.getTimerCount()).toBe(1);
    act(() => {
      void rs.advanceTimersByTime(800);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    const replacement = FakeWebSocket.instances[1]!;
    act(() => {
      replacement.open();
      void rs.advanceTimersByTime(300_000);
    });
    expect(rs.getTimerCount()).toBe(0);
    expect(result.current.status).toBe("open");
    expect(replacement.closeCalls).toBe(0);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  test("clears the handshake deadline when the panel is disabled", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result, rerender } = renderHook(
      ({ enabled }) => useBrowserStream("thread-1", enabled),
      { initialProps: { enabled: true } },
    );
    act(() => {
      void rs.advanceTimersByTime(5_000);
    });
    rerender({ enabled: false });
    expect(rs.getTimerCount()).toBe(0);

    act(() => {
      void rs.advanceTimersByTime(60_000);
    });
    expect(result.current.status).toBe("idle");
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0]!.closeCalls).toBe(1);
  });

  test("clears the handshake deadline on unmount", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { unmount } = renderHook(() => useBrowserStream("thread-1", true));
    act(() => {
      void rs.advanceTimersByTime(5_000);
    });
    unmount();
    expect(rs.getTimerCount()).toBe(0);

    act(() => {
      void rs.advanceTimersByTime(60_000);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0]!.closeCalls).toBe(1);
  });

  test("a thread change gives the new socket its own deadline and ignores stale events", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result, rerender } = renderHook(
      ({ threadId }) => useBrowserStream(threadId, true),
      { initialProps: { threadId: "thread-1" } },
    );
    const first = FakeWebSocket.instances[0]!;
    act(() => {
      void rs.advanceTimersByTime(5_000);
    });
    rerender({ threadId: "thread-2" });
    const replacement = FakeWebSocket.instances[1]!;
    expect(first.closeCalls).toBe(1);
    expect(replacement.url).toBe("ws://example.test/thread-2");

    act(() => {
      first.open();
      first.onerror?.();
      first.disconnect();
      void rs.advanceTimersByTime(5_000);
    });
    expect(result.current.status).toBe("connecting");
    expect(replacement.closeCalls).toBe(0);
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => {
      replacement.open();
      void rs.advanceTimersByTime(300_000);
    });
    expect(result.current.status).toBe("open");
    expect(replacement.closeCalls).toBe(0);
    expect(rs.getTimerCount()).toBe(0);
  });

  test("ignores late open, frame, error and close events from a timed-out attempt", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result } = renderHook(() => useBrowserStream("thread-1", true));
    const first = FakeWebSocket.instances[0]!;
    act(() => {
      void rs.advanceTimersByTime(10_000);
    });
    expect(first.closeCalls).toBe(1);

    act(() => {
      first.open();
      first.onmessage?.({
        data: JSON.stringify({ type: "url", url: "https://stale.example/" }),
      } as MessageEvent);
      first.onerror?.();
      first.disconnect();
    });
    expect(result.current.status).toBe("closed");
    expect(result.current.liveUrl).toBeNull();
    expect(rs.getTimerCount()).toBe(1);

    act(() => {
      void rs.advanceTimersByTime(800);
    });
    const replacement = FakeWebSocket.instances[1]!;
    act(() => {
      replacement.open();
      first.open();
      first.onerror?.();
      first.disconnect();
      void rs.advanceTimersByTime(300_000);
    });
    expect(result.current.status).toBe("open");
    expect(replacement.closeCalls).toBe(0);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(rs.getTimerCount()).toBe(0);
  });

  test("stalled handshakes stop after the existing six-reconnect limit", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result } = renderHook(() => useBrowserStream("thread-1", true));
    for (let attempt = 0; attempt <= 6; attempt += 1) {
      const socket = FakeWebSocket.instances[attempt]!;
      act(() => {
        void rs.advanceTimersByTime(10_000);
      });
      expect(socket.closeCalls).toBe(1);
      expect(result.current.status).toBe("closed");
      act(() => {
        // A late open must not replenish a nonzero retry budget.
        socket.open();
        socket.disconnect();
      });
      expect(result.current.status).toBe("closed");

      if (attempt < 6) {
        const delay = Math.min(800 * 2 ** attempt, 10_000);
        act(() => {
          void rs.advanceTimersByTime(delay);
        });
        expect(FakeWebSocket.instances).toHaveLength(attempt + 2);
      }
    }

    act(() => {
      void rs.advanceTimersByTime(300_000);
    });
    expect(FakeWebSocket.instances).toHaveLength(7);
    expect(result.current.closedReason).toBe("handshake_timeout");
    expect(result.current.status).toBe("closed");
    expect(rs.getTimerCount()).toBe(0);
  });

  test("preserves a timeout reason through retries and stale events until open", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result } = renderHook(() => useBrowserStream("thread-1", true));
    const first = FakeWebSocket.instances[0]!;
    expect(result.current.closedReason).toBeNull();
    act(() => {
      void rs.advanceTimersByTime(10_000);
      first.onerror?.();
      first.disconnect();
      first.open();
    });
    expect(result.current.closedReason).toBe("handshake_timeout");

    act(() => {
      void rs.advanceTimersByTime(800);
      first.onerror?.();
    });
    expect(result.current.status).toBe("connecting");
    expect(result.current.closedReason).toBe("handshake_timeout");
    act(() => FakeWebSocket.instances[1]!.open());
    expect(result.current.status).toBe("open");
    expect(result.current.closedReason).toBeNull();
  });

  test.each(["error", "close"] as const)(
    "reports a socket %s separately from a handshake timeout",
    (event) => {
      rs.useFakeTimers();
      rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

      const { result } = renderHook(() => useBrowserStream("thread-1", true));
      const socket = FakeWebSocket.instances[0]!;
      act(() => {
        if (event === "error") socket.onerror?.();
        else socket.disconnect();
      });
      expect(result.current.status).toBe("closed");
      expect(result.current.closedReason).toBe("connection_failed");
      act(() => {
        void rs.advanceTimersByTime(800);
      });
      act(() => FakeWebSocket.instances[1]!.open());
      expect(result.current.closedReason).toBeNull();
    },
  );

  test("clears the failure reason when disabled or moved to another thread", () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    const { result, rerender } = renderHook(
      ({ threadId, enabled }) => useBrowserStream(threadId, enabled),
      { initialProps: { threadId: "thread-1", enabled: true } },
    );
    act(() => {
      void rs.advanceTimersByTime(10_000);
    });
    expect(result.current.closedReason).toBe("handshake_timeout");
    rerender({ threadId: "thread-1", enabled: false });
    expect(result.current.closedReason).toBeNull();
    rerender({ threadId: "thread-1", enabled: true });
    expect(result.current.closedReason).toBeNull();
    act(() => {
      void rs.advanceTimersByTime(10_000);
    });
    expect(result.current.closedReason).toBe("handshake_timeout");
    const retired = FakeWebSocket.instances.at(-1)!;
    rerender({ threadId: "thread-2", enabled: true });
    act(() => retired.onerror?.());
    expect(result.current.status).toBe("connecting");
    expect(result.current.closedReason).toBeNull();
  });

  test("keeps a successfully reconnected socket instead of recreating it", async () => {
    rs.useFakeTimers();
    rs.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

    renderHook(() => useBrowserStream("thread-1", true));
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      FakeWebSocket.instances[0]?.open();
      FakeWebSocket.instances[0]?.disconnect();
    });

    act(() => {
      void rs.advanceTimersByTime(800);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => {
      FakeWebSocket.instances[1]?.open();
    });

    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1]?.closeCalls).toBe(0);

    act(() => {
      FakeWebSocket.instances[1]?.disconnect();
      void rs.advanceTimersByTime(799);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => {
      void rs.advanceTimersByTime(1);
    });
    expect(FakeWebSocket.instances).toHaveLength(3);
  });
});
