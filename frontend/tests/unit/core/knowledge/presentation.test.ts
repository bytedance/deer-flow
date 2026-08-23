import { describe, expect, test } from "@rstest/core";

import {
  datasetParsingState,
  documentRunKind,
  validateKnowledgeUpload,
} from "@/core/knowledge/presentation";

describe("knowledge presentation helpers", () => {
  test("derives parsing progress from all five watcher counters", () => {
    expect(
      datasetParsingState({
        id: "dataset-1",
        name: "Policies",
        unstart_count: 1,
        running_count: 1,
        cancel_count: 0,
        done_count: 2,
        fail_count: 0,
      }),
    ).toEqual({ kind: "parsing", completed: 2, total: 4, percent: 50 });
  });

  test("distinguishes failure, ready, and empty datasets", () => {
    expect(
      datasetParsingState({
        id: "failed",
        name: "Failed",
        document_count: 2,
        fail_count: 1,
        done_count: 1,
      }).kind,
    ).toBe("failed");
    expect(
      datasetParsingState({
        id: "ready",
        name: "Ready",
        document_count: 2,
        done_count: 2,
      }).kind,
    ).toBe("ready");
    expect(
      datasetParsingState({
        id: "empty",
        name: "Empty",
        document_count: 0,
      }).kind,
    ).toBe("empty");
  });

  test("normalizes RAGFlow document run values", () => {
    expect(documentRunKind("RUNNING")).toBe("parsing");
    expect(documentRunKind("DONE")).toBe("ready");
    expect(documentRunKind("FAIL")).toBe("failed");
    expect(documentRunKind("CANCEL")).toBe("cancelled");
    expect(documentRunKind(undefined)).toBe("unparsed");
  });

  test("mirrors the Gateway upload limits before sending", () => {
    const elevenFiles = Array.from(
      { length: 11 },
      (_, index) =>
        new File(["x"], `file-${index}.txt`, { type: "text/plain" }),
    );
    expect(validateKnowledgeUpload(elevenFiles)).toBe("too_many_files");

    const oversized = {
      name: "large.pdf",
      size: 50 * 1024 * 1024 + 1,
    } as File;
    expect(validateKnowledgeUpload([oversized])).toBe("file_too_large");
    expect(
      validateKnowledgeUpload([
        { name: "one.bin", size: 50 * 1024 * 1024 } as File,
        { name: "two.bin", size: 50 * 1024 * 1024 } as File,
        { name: "three.bin", size: 1 } as File,
      ]),
    ).toBe("request_too_large");
    expect(validateKnowledgeUpload([])).toBe("no_files");
  });
});
