import { afterEach, expect, rs, test } from "@rstest/core";
import {
  focusManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";

import { useProjectMemory } from "@/core/projects/memory";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));

afterEach(() => {
  cleanup();
  focusManager.setFocused(undefined);
  rs.useRealTimers();
  mocks.fetch.mockReset();
});

test("project memory pauses interval polling in background and resumes in foreground", async () => {
  rs.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "Date",
    ],
  });
  focusManager.setFocused(false);
  mocks.fetch.mockResolvedValue({
    ok: true,
    json: async () => ({ enabled: true, facts: [], max_facts: 30 }),
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  try {
    renderHook(() => useProjectMemory("p1"), { wrapper });
    await act(() => rs.advanceTimersByTimeAsync(1));
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    await act(() => rs.advanceTimersByTimeAsync(30_000));
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    await act(async () => {
      focusManager.setFocused(true);
      await rs.advanceTimersByTimeAsync(10_001);
    });
    expect(mocks.fetch.mock.calls.length).toBeGreaterThan(1);
  } finally {
    cleanup();
    client.clear();
  }
});
