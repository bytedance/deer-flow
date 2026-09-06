import { describe, expect, test } from "@rstest/core";

import {
  buildKnowledgeScopeSnapshot,
  cloneKnowledgeScopeSelection,
  readKnowledgeScopeSnapshot,
  type KnowledgeScopeSelection,
} from "@/core/knowledge/scope";

describe("knowledge scope snapshots", () => {
  test("builds selected datasets and file filters with bounded display labels", () => {
    const snapshot = buildKnowledgeScopeSnapshot({
      mode: "selected",
      datasets: [
        {
          id: " dataset-1 ",
          name: "Policies",
          documents: {
            mode: "selected",
            items: [
              { id: "doc-1", name: "Leave.pdf" },
              { id: "doc-1", name: "Duplicate.pdf" },
            ],
          },
        },
        {
          id: "dataset-2",
          name: "Handbook",
          documents: { mode: "all" },
        },
      ],
    });

    expect(snapshot).toEqual({
      version: 1,
      mode: "selected",
      dataset_ids: ["dataset-1", "dataset-2"],
      document_filters: [{ dataset_id: "dataset-1", document_ids: ["doc-1"] }],
      display: {
        datasets: [
          {
            id: "dataset-1",
            name: "Policies",
            documents: [{ id: "doc-1", name: "Leave.pdf" }],
          },
          { id: "dataset-2", name: "Handbook" },
        ],
      },
    });
  });

  test("rejects an empty selected document filter", () => {
    expect(() =>
      buildKnowledgeScopeSnapshot({
        mode: "selected",
        datasets: [
          {
            id: "dataset-1",
            name: "Policies",
            documents: { mode: "selected", items: [] },
          },
        ],
      }),
    ).toThrow(/at least one document/i);
  });

  test("omits overlong display names without truncating execution ids", () => {
    const snapshot = buildKnowledgeScopeSnapshot({
      mode: "selected",
      datasets: [
        {
          id: "dataset-1",
          name: "x".repeat(257),
          documents: { mode: "all" },
        },
      ],
    });

    expect(snapshot.dataset_ids).toEqual(["dataset-1"]);
    expect(snapshot.display).toBeUndefined();
  });

  test("counts astral Unicode characters as code points", () => {
    const emojiName = "😀".repeat(256);
    const snapshot = buildKnowledgeScopeSnapshot({
      mode: "selected",
      datasets: [
        {
          id: "dataset-1",
          name: emojiName,
          documents: { mode: "all" },
        },
      ],
    });

    expect(snapshot.display?.datasets[0]?.name).toBe(emojiName);
  });

  test("clones nested selection state for immutable message snapshots", () => {
    const selection: KnowledgeScopeSelection = {
      mode: "selected",
      datasets: [
        {
          id: "dataset-1",
          name: "Policies",
          documents: {
            mode: "selected",
            items: [{ id: "doc-1", name: "Leave.pdf" }],
          },
        },
      ],
    };
    const cloned = cloneKnowledgeScopeSelection(selection);
    if (selection.mode === "selected") selection.datasets[0]!.name = "Renamed";

    expect(cloned).not.toBe(selection);
    expect(cloned.mode === "selected" && cloned.datasets[0]?.name).toBe(
      "Policies",
    );
  });

  test("reads only recognized version-one modes", () => {
    expect(readKnowledgeScopeSnapshot({ version: 1, mode: "all" })).toEqual({
      version: 1,
      mode: "all",
    });
    expect(readKnowledgeScopeSnapshot({ version: 2, mode: "all" })).toBeNull();
    expect(
      readKnowledgeScopeSnapshot({
        version: 1,
        mode: "selected",
        dataset_ids: ["dataset-1"],
        document_filters: [{ dataset_id: "dataset-1", document_ids: null }],
      }),
    ).toBeNull();
  });
});
