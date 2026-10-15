import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

import { startConnectionPoll } from "@/core/channels/connect-poll";
import type { ChannelConnection } from "@/core/channels/types";

function connection(provider: string, status: string): ChannelConnection {
  return {
    id: `${provider}-1`,
    provider,
    status,
    scopes: [],
    metadata: {},
  };
}

beforeEach(() => {
  rs.useFakeTimers();
});

afterEach(() => {
  rs.useRealTimers();
});

describe("startConnectionPoll", () => {
  test("polls connections until the provider is connected, then resolves once", async () => {
    const responses: ChannelConnection[][] = [
      [connection("telegram", "pending")],
      [connection("telegram", "connected")],
    ];
    const fetchConnections = rs.fn(async () => responses.shift() ?? []);
    const onConnected = rs.fn();

    startConnectionPoll({
      provider: "telegram",
      expiresInSeconds: 600,
      fetchConnections,
      onConnected,
      intervalMs: 1000,
    });

    await rs.advanceTimersByTimeAsync(1000);
    expect(fetchConnections).toHaveBeenCalledTimes(1);
    expect(onConnected).not.toHaveBeenCalled();

    await rs.advanceTimersByTimeAsync(1000);
    expect(fetchConnections).toHaveBeenCalledTimes(2);
    expect(onConnected).toHaveBeenCalledTimes(1);

    // No further polling after the connection resolves.
    await rs.advanceTimersByTimeAsync(5000);
    expect(fetchConnections).toHaveBeenCalledTimes(2);
  });

  test("cancel() stops scheduled polling and fires no further fetches", async () => {
    const fetchConnections = rs.fn(async () => [
      connection("telegram", "pending"),
    ]);
    const handle = startConnectionPoll({
      provider: "telegram",
      expiresInSeconds: 600,
      fetchConnections,
      onConnected: rs.fn(),
      intervalMs: 1000,
    });

    await rs.advanceTimersByTimeAsync(1000);
    expect(fetchConnections).toHaveBeenCalledTimes(1);

    handle.cancel();
    await rs.advanceTimersByTimeAsync(10000);
    expect(fetchConnections).toHaveBeenCalledTimes(1);
  });

  test("a non-finite expires_in falls back to a finite deadline and terminates", async () => {
    const fetchConnections = rs.fn(async () => [
      connection("telegram", "pending"),
    ]);
    let nowValue = 0;
    startConnectionPoll({
      provider: "telegram",
      expiresInSeconds: Number.NaN,
      fetchConnections,
      onConnected: rs.fn(),
      intervalMs: 1000,
      now: () => nowValue,
    });

    nowValue = 1;
    await rs.advanceTimersByTimeAsync(1000);
    expect(fetchConnections).toHaveBeenCalledTimes(1);

    // Jump past the fallback expiry window: the loop must stop instead of
    // running forever (Date.now() >= NaN would otherwise never be true).
    nowValue = 10_000_000;
    await rs.advanceTimersByTimeAsync(1000);
    expect(fetchConnections).toHaveBeenCalledTimes(2);

    await rs.advanceTimersByTimeAsync(10000);
    expect(fetchConnections).toHaveBeenCalledTimes(2);
  });
});
