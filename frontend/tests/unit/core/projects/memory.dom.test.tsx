import { afterEach, expect, rs, test } from "@rstest/core";
import {
  focusManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { usePatchProject, useProject } from "@/core/projects/hooks";
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

test("a stale save refetches the promoted fact and a reviewed merge updates the editor cache", async () => {
  const project = {
    id: "p1",
    name: "Finance",
    instructions: "",
    presentation: {},
    status: "active",
    created_at: "",
    updated_at: "",
  };
  const promoted = "- Reports exclude tax";
  mocks.fetch
    .mockResolvedValueOnce(Response.json(project))
    .mockResolvedValueOnce(
      Response.json(
        { detail: "Project instructions changed." },
        { status: 409 },
      ),
    )
    .mockResolvedValueOnce(
      Response.json({ ...project, instructions: promoted }),
    );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const { result } = renderHook(
    () => ({ project: useProject("p1"), patch: usePatchProject() }),
    {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  try {
    await waitFor(() =>
      expect(result.current.project.data?.instructions).toBe(""),
    );
    await act(async () => {
      await expect(
        result.current.patch.mutateAsync({
          projectId: "p1",
          input: { instructions: "Use USD", expected_instructions: "" },
        }),
      ).rejects.toThrow("Project instructions changed.");
    });
    const [, request] = mocks.fetch.mock.calls[1] as [string, RequestInit];
    expect(request.method).toBe("PATCH");
    expect(JSON.parse(request.body as string)).toEqual({
      instructions: "Use USD",
      expected_instructions: "",
    });
    await waitFor(() =>
      expect(result.current.project.data?.instructions).toBe(promoted),
    );

    const merged = `Use USD\n${promoted}`;
    mocks.fetch
      .mockResolvedValueOnce(
        Response.json({ ...project, instructions: merged }),
      )
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await act(async () => {
      await result.current.patch.mutateAsync({
        projectId: "p1",
        input: { instructions: merged, expected_instructions: promoted },
      });
    });
    await waitFor(() =>
      expect(result.current.project.isRefetchError).toBe(true),
    );
    expect(result.current.project.data?.instructions).toBe(merged);
  } finally {
    cleanup();
    client.clear();
  }
});
