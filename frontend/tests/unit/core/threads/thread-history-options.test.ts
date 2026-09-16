import { describe, expect, it } from "@rstest/core";

import { THREAD_HISTORY_QUERY_POLICY } from "@/core/threads/hooks";

describe("thread history query policy", () => {
  it("does not refetch immutable pages on window focus", () => {
    expect(THREAD_HISTORY_QUERY_POLICY).toEqual({
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1_000,
    });
  });
});
