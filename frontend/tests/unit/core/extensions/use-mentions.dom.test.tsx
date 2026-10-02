import { afterEach, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";

import { useExtensionMentions } from "@/core/extensions/use-mentions";

let viewer = "alice";
const search = rs.fn();
let entries = [
  {
    namespace: "test.team",
    viewer_id: viewer,
    module: "team",
    entry: null,
    title: "Team",
    description: "",
    settings: { enabled: true },
    extension: {
      apiVersion: 1,
      module: "team",
      mentionProviders: [{ id: "members", label: "Members", search }],
    },
  },
];
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: viewer } }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ locale: "en-US" }) }));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({
    data: entries,
    isPending: false,
    isError: false,
  }),
}));
afterEach(() => {
  cleanup();
  search.mockReset();
  viewer = "alice";
});
it("cancels old queries and fences results across query, thread, viewer and unmount", async () => {
  let release!: (value: { id: string; label: string }[]) => void;
  let signal!: AbortSignal;
  search.mockImplementationOnce((_query, context) => {
    signal = context.signal;
    return new Promise((resolve) => {
      release = resolve;
    });
  });
  search.mockResolvedValue([{ id: "new", label: "Current" }]);
  const { result, rerender, unmount } = renderHook(
    ({ query, threadId }) => useExtensionMentions(query, threadId),
    { initialProps: { query: "old", threadId: "one" } },
  );
  await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
  rerender({ query: "new", threadId: "two" });
  expect(signal.aborted).toBe(true);
  await waitFor(() => expect(result.current.items[0]?.id).toBe("new"));
  await act(async () => {
    release([{ id: "old", label: "Stale" }]);
  });
  expect(result.current.items[0]?.id).toBe("new");
  viewer = "bob";
  rerender({ query: "new", threadId: "two" });
  expect(result.current.items).toEqual([]);
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.items).toEqual([]);
  entries = entries.map((entry) => ({ ...entry, viewer_id: viewer }));
  rerender({ query: "last", threadId: "three" });
  await waitFor(() => expect(search).toHaveBeenCalledTimes(3));
  unmount();
  expect(search.mock.calls[2]![1].signal.aborted).toBe(true);
});
