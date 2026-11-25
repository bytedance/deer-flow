import { expect, it } from "@rstest/core";

import { readingStateAccess } from "@/core/artifacts/reading-state";

it("isolates viewers, files and content versions; stale callbacks cannot write", () => {
  const a = readingStateAccess("viewer-a", "file-a:hash-1");
  a.set({ page: 3, scroll: [0, 500] });
  const copy = a.get() as { page: number };
  copy.page = 99;
  expect(a.get()).toEqual({ page: 3, scroll: [0, 500] });
  expect(readingStateAccess("viewer-a", "file-a:hash-2").get()).toBeUndefined();
  const b = readingStateAccess("viewer-b", "file-a:hash-1");
  expect(b.get()).toBeUndefined();
  a.set({ page: 20 });
  expect(b.get()).toBeUndefined();
  expect(readingStateAccess("viewer-a", "file-a:hash-1").get()).toBeUndefined();
});

it("bounds state size and file count without evicting valid state for rejected writes", () => {
  const a = readingStateAccess("bounded-viewer", "first");
  a.set({ page: 1 });
  a.set("x".repeat(20_000));
  a.set({ circular: BigInt(1) });
  expect(a.get()).toEqual({ page: 1 });
  for (let i = 0; i < 50; i++)
    readingStateAccess("bounded-viewer", String(i)).set({ page: i });
  expect(a.get()).toBeUndefined();
  expect(readingStateAccess("bounded-viewer", "49").get()).toEqual({
    page: 49,
  });
});
