import { afterEach, expect, rs, test } from "@rstest/core";

import {
  readProjectAttachments,
  retireProjectAttachments,
  stageProjectAttachment,
} from "@/core/projects/composer-attach";
import type { AttachProjectDocumentResult } from "@/core/projects/types";

const ATTACHMENT: AttachProjectDocumentResult = {
  filename: "roadmap.md",
  size_bytes: 2048,
  virtual_path: "/mnt/user-data/uploads/roadmap.md",
  artifact_url:
    "/api/threads/thread-1/artifacts/mnt/user-data/uploads/roadmap.md",
};

const OTHER: AttachProjectDocumentResult = {
  filename: "notes.txt",
  size_bytes: 128,
  virtual_path: "/mnt/user-data/uploads/notes.txt",
  artifact_url:
    "/api/threads/thread-1/artifacts/mnt/user-data/uploads/notes.txt",
};

afterEach(() => {
  rs.restoreAllMocks();
  window.sessionStorage.clear();
});

test("staged attachments append to the thread's pending list and never consume on read", () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  stageProjectAttachment("thread-1", OTHER);

  // A different thread sees nothing.
  expect(readProjectAttachments("thread-2")).toEqual([]);

  // Read-only: repeated reads keep returning the pending entries — nothing
  // is consumed until submission or explicit removal.
  expect(readProjectAttachments("thread-1")).toEqual([ATTACHMENT, OTHER]);
  expect(readProjectAttachments("thread-1")).toEqual([ATTACHMENT, OTHER]);
});

test("re-staging the same document refreshes its entry instead of duplicating it", () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  stageProjectAttachment("thread-1", OTHER);
  const refreshed = { ...ATTACHMENT, size_bytes: 4096 };
  stageProjectAttachment("thread-1", refreshed);

  expect(readProjectAttachments("thread-1")).toEqual([OTHER, refreshed]);
});

test("a corrupt staged payload is dropped, not thrown", () => {
  window.sessionStorage.setItem(
    "deerflow.project-attachment.thread-1",
    "{not json",
  );
  expect(readProjectAttachments("thread-1")).toEqual([]);
  // The corrupt entry was cleared along the way.
  expect(
    window.sessionStorage.getItem("deerflow.project-attachment.thread-1"),
  ).toBeNull();
});

test("unavailable storage access leaves staging, reading and retirement usable", () => {
  rs.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
    throw new DOMException("Storage denied", "SecurityError");
  });

  expect(() => stageProjectAttachment("thread-1", ATTACHMENT)).not.toThrow();
  expect(readProjectAttachments("thread-1")).toEqual([]);
  expect(() =>
    retireProjectAttachments("thread-1", [ATTACHMENT]),
  ).not.toThrow();
});

test("denied reads return no pending attachments without interrupting staging or retirement", () => {
  rs.spyOn(window.sessionStorage, "getItem").mockImplementation(() => {
    throw new DOMException("Read denied", "SecurityError");
  });

  expect(readProjectAttachments("thread-1")).toEqual([]);
  expect(() => stageProjectAttachment("thread-1", ATTACHMENT)).not.toThrow();
  expect(() =>
    retireProjectAttachments("thread-1", [ATTACHMENT]),
  ).not.toThrow();
});

test("staging preserves pending attachments when their stored list cannot be read", () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  rs.spyOn(window.sessionStorage, "getItem").mockImplementationOnce(() => {
    throw new DOMException("Read denied", "SecurityError");
  });

  stageProjectAttachment("thread-1", OTHER);

  expect(readProjectAttachments("thread-1")).toEqual([ATTACHMENT]);
});

test("retiring sent attachments preserves the list when it cannot be read", () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  stageProjectAttachment("thread-1", OTHER);
  rs.spyOn(window.sessionStorage, "getItem").mockImplementationOnce(() => {
    throw new DOMException("Read denied", "SecurityError");
  });

  retireProjectAttachments("thread-1", [ATTACHMENT]);

  expect(readProjectAttachments("thread-1")).toEqual([ATTACHMENT, OTHER]);
});

test("quota failures do not interrupt staging or retirement of a partial list", () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  stageProjectAttachment("thread-1", OTHER);
  rs.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
    throw new DOMException("Storage full", "QuotaExceededError");
  });

  expect(() => stageProjectAttachment("thread-1", OTHER)).not.toThrow();
  expect(() =>
    retireProjectAttachments("thread-1", [ATTACHMENT]),
  ).not.toThrow();
  // A failed persistence write leaves the old stored list untouched.
  expect(readProjectAttachments("thread-1")).toEqual([ATTACHMENT, OTHER]);
});

test("a failed cleanup does not interrupt reading a corrupt payload", () => {
  window.sessionStorage.setItem(
    "deerflow.project-attachment.thread-1",
    "{not json",
  );
  rs.spyOn(window.sessionStorage, "removeItem").mockImplementation(() => {
    throw new DOMException("blocked", "SecurityError");
  });

  expect(() => readProjectAttachments("thread-1")).not.toThrow();
  expect(readProjectAttachments("thread-1")).toEqual([]);
});

test("a failed storage removal does not interrupt retiring sent attachments", () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  rs.spyOn(window.sessionStorage, "removeItem").mockImplementation(() => {
    throw new DOMException("blocked", "SecurityError");
  });

  expect(() =>
    retireProjectAttachments("thread-1", [ATTACHMENT]),
  ).not.toThrow();
});

test("a failed storage write does not interrupt retiring remaining attachments", () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  stageProjectAttachment("thread-1", OTHER);
  rs.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
    throw new DOMException("full", "QuotaExceededError");
  });

  expect(() =>
    retireProjectAttachments("thread-1", [ATTACHMENT]),
  ).not.toThrow();
});

test("retirement keeps later attachments and other threads' pending lists", () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  stageProjectAttachment("thread-1", OTHER);
  stageProjectAttachment("thread-2", ATTACHMENT);

  retireProjectAttachments("thread-1", [ATTACHMENT]);

  expect(readProjectAttachments("thread-1")).toEqual([OTHER]);
  expect(readProjectAttachments("thread-2")).toEqual([ATTACHMENT]);
  retireProjectAttachments("thread-1", [OTHER]);
  expect(readProjectAttachments("thread-1")).toEqual([]);
});

test("the pre-list single-object payload shape reads as a one-element list", () => {
  window.sessionStorage.setItem(
    "deerflow.project-attachment.thread-1",
    JSON.stringify(ATTACHMENT),
  );

  expect(readProjectAttachments("thread-1")).toEqual([ATTACHMENT]);
});
