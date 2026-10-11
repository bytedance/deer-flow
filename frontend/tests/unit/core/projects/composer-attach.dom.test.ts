import { afterEach, expect, test } from "@rstest/core";

import {
  readProjectAttachments,
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

test("the pre-list single-object payload shape reads as a one-element list", () => {
  window.sessionStorage.setItem(
    "deerflow.project-attachment.thread-1",
    JSON.stringify(ATTACHMENT),
  );

  expect(readProjectAttachments("thread-1")).toEqual([ATTACHMENT]);
});
