import { expect, test, rs } from "@rstest/core";

import {
  buildThreadsSearchQueryOptions,
  DEFAULT_THREAD_SEARCH_PARAMS,
  THREAD_SEARCH_REFETCH_INTERVAL_MS,
} from "@/core/threads/thread-search-query";

test("thread search query refreshes so IM-created sessions appear in the sidebar", () => {
  const search = rs.fn();
  const options = buildThreadsSearchQueryOptions(
    { threads: { search } },
    DEFAULT_THREAD_SEARCH_PARAMS,
  );

  expect(options.refetchInterval).toBe(THREAD_SEARCH_REFETCH_INTERVAL_MS);
  expect(options.refetchIntervalInBackground).toBe(false);
  expect(options.refetchOnWindowFocus).toBe(false);
});
