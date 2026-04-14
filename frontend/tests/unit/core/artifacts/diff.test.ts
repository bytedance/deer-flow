import { expect, test } from "vitest";

import { buildThreadFileDiff } from "@/core/artifacts/diff";

test("buildThreadFileDiff marks added, removed, and modified lines", () => {
  const diff = buildThreadFileDiff({
    beforeContent: ["alpha", "beta", "gamma", "delta"].join("\n"),
    afterContent: ["alpha", "beta updated", "gamma", "epsilon"].join("\n"),
  });

  expect(diff.summary).toEqual({
    added: 0,
    removed: 0,
    modified: 2,
  });
  expect(diff.lines).toEqual([
    {
      kind: "context",
      beforeLineNumber: 1,
      afterLineNumber: 1,
      beforeContent: "alpha",
      afterContent: "alpha",
    },
    {
      kind: "modified",
      beforeLineNumber: 2,
      afterLineNumber: 2,
      beforeContent: "beta",
      afterContent: "beta updated",
    },
    {
      kind: "context",
      beforeLineNumber: 3,
      afterLineNumber: 3,
      beforeContent: "gamma",
      afterContent: "gamma",
    },
    {
      kind: "modified",
      beforeLineNumber: 4,
      afterLineNumber: 4,
      beforeContent: "delta",
      afterContent: "epsilon",
    },
  ]);
});

test("buildThreadFileDiff preserves asymmetric add and remove hunks", () => {
  const diff = buildThreadFileDiff({
    beforeContent: ["alpha", "beta", "gamma"].join("\n"),
    afterContent: ["alpha", "beta", "delta", "epsilon"].join("\n"),
  });

  expect(diff.summary).toEqual({
    added: 1,
    removed: 0,
    modified: 1,
  });
  expect(diff.lines).toEqual([
    {
      kind: "context",
      beforeLineNumber: 1,
      afterLineNumber: 1,
      beforeContent: "alpha",
      afterContent: "alpha",
    },
    {
      kind: "context",
      beforeLineNumber: 2,
      afterLineNumber: 2,
      beforeContent: "beta",
      afterContent: "beta",
    },
    {
      kind: "modified",
      beforeLineNumber: 3,
      afterLineNumber: 3,
      beforeContent: "gamma",
      afterContent: "delta",
    },
    {
      kind: "added",
      beforeLineNumber: null,
      afterLineNumber: 4,
      beforeContent: "",
      afterContent: "epsilon",
    },
  ]);
});
