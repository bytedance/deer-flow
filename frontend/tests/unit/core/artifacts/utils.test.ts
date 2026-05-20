import { expect, test, vi } from "vitest";

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://localhost:2026",
}));

import {
  isArtifactVirtualPath,
  normalizeArtifactVirtualPath,
  resolveArtifactURL,
  urlOfArtifact,
} from "@/core/artifacts/utils";

test("recognizes artifact virtual paths with and without leading slash", () => {
  expect(isArtifactVirtualPath("/mnt/user-data/outputs/result.docx")).toBe(
    true,
  );
  expect(isArtifactVirtualPath("mnt/user-data/outputs/result.docx")).toBe(true);
  expect(isArtifactVirtualPath("/workspace/chats/thread-1")).toBe(false);
});

test("normalizes artifact virtual paths to include a leading slash", () => {
  expect(
    normalizeArtifactVirtualPath("mnt/user-data/outputs/result.docx"),
  ).toBe("/mnt/user-data/outputs/result.docx");
  expect(
    normalizeArtifactVirtualPath("/mnt/user-data/outputs/result.docx"),
  ).toBe("/mnt/user-data/outputs/result.docx");
});

test("builds artifact URLs for paths with and without leading slash", () => {
  expect(
    resolveArtifactURL("/mnt/user-data/outputs/result.docx", "thread-1"),
  ).toBe(
    "http://localhost:2026/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.docx",
  );
  expect(
    resolveArtifactURL("mnt/user-data/outputs/result.docx", "thread-1"),
  ).toBe(
    "http://localhost:2026/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.docx",
  );
});

test("normalizes artifact URLs for direct and mock downloads", () => {
  expect(
    urlOfArtifact({
      filepath: "mnt/user-data/outputs/result.docx",
      threadId: "thread-1",
    }),
  ).toBe(
    "http://localhost:2026/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.docx",
  );
  expect(
    urlOfArtifact({
      filepath: "mnt/user-data/outputs/result.docx",
      threadId: "thread-1",
      download: true,
      isMock: true,
    }),
  ).toBe(
    "http://localhost:2026/mock/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.docx?download=true",
  );
});
