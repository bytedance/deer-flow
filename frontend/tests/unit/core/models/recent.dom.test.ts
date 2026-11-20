import { afterEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

import {
  rememberModel,
  recentKey,
  useRecentModels,
} from "@/core/models/recent";

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  localStorage.clear();
});
it("synchronizes mounted pickers, bounds history and isolates accounts", () => {
  const first = renderHook(({ user }) => useRecentModels(user), {
    initialProps: { user: "recent-a" as string | null },
  });
  const second = renderHook(() => useRecentModels("recent-a"));
  act(() => {
    for (let i = 0; i < 12; i++) rememberModel("recent-a", `model-${i}`);
  });
  expect(first.result.current).toHaveLength(8);
  expect(second.result.current).toEqual(first.result.current);
  act(() => rememberModel("recent-a", "model-7"));
  expect(first.result.current[0]).toBe("model-7");
  first.rerender({ user: null });
  expect(first.result.current).toEqual([]);
  first.rerender({ user: "recent-b" });
  expect(first.result.current).toEqual([]);
  act(() => {
    localStorage.removeItem(recentKey("recent-a"));
    window.dispatchEvent(new Event("storage"));
  });
  expect(second.result.current).toEqual([]);
});
it("continues in memory when storage writes fail", () => {
  rs.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const result = renderHook(() => useRecentModels("blocked-recent"));
  act(() => rememberModel("blocked-recent", "a"));
  act(() => rememberModel("blocked-recent", "b"));
  expect(result.result.current).toEqual(["b", "a"]);
});
