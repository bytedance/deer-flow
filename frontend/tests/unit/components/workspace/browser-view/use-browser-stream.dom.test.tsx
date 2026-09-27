import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

rs.mock("@/components/workspace/browser-view/api", () => ({
  browserStreamURL: (threadId: string) => `ws://example.test/${threadId}`,
}));

import { useBrowserStream } from "@/components/workspace/browser-view/use-browser-stream";

class FakeWebSocket {
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = 0;
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
