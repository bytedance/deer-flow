import { beforeEach, describe, expect, it } from "vitest";

import {
  __test_only,
  getLaunchThread,
  setLaunchThread,
} from "@/core/deep-link/launch-session";

const { pruneLaunchSessionMap, MAX_LAUNCH_SESSION_ENTRIES } = __test_only;

describe("launch-session", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("stores and restores a thread for the same route key", () => {
    setLaunchThread("launch-1", "thread-1", "agent:daily");

    expect(getLaunchThread("launch-1", "agent:daily")).toBe("thread-1");
  });

  it("does not restore a thread for a different route key", () => {
    setLaunchThread("launch-1", "thread-1", "agent:daily");

    expect(getLaunchThread("launch-1", "agent:weekly")).toBeNull();
  });

  it("prunes old entries to the configured max size", () => {
    const entries = Object.fromEntries(
      Array.from({ length: MAX_LAUNCH_SESSION_ENTRIES + 5 }, (_, index) => [
        `launch-${index}`,
        {
          threadId: `thread-${index}`,
          routeKey: "agent:test",
          updatedAt: index,
        },
      ]),
    );

    const pruned = pruneLaunchSessionMap(entries);

    expect(Object.keys(pruned)).toHaveLength(MAX_LAUNCH_SESSION_ENTRIES);
    expect(pruned["launch-0"]).toBeUndefined();
    expect(pruned[`launch-${MAX_LAUNCH_SESSION_ENTRIES + 4}`]).toBeDefined();
  });
});
