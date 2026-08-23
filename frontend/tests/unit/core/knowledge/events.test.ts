import { describe, expect, test } from "@rstest/core";

import {
  applyKnowledgeEventToDatasets,
  parseKnowledgeEvent,
} from "@/core/knowledge/events";
import type { KnowledgeDataset } from "@/core/knowledge/types";

const DATASETS: KnowledgeDataset[] = [
  {
    id: "dataset-1",
    name: "Policies",
    document_count: 3,
  },
  { id: "dataset-2", name: "Engineering", document_count: 1 },
];

describe("knowledge SSE events", () => {
  test("parses only supported events with a dataset id", () => {
    expect(
      parseKnowledgeEvent("dataset_parsing_progress", {
        data: JSON.stringify({
          dataset_id: "dataset-1",
          unstart_count: 1,
          running_count: 1,
          cancel_count: 0,
          done_count: 1,
          fail_count: 0,
        }),
      } as MessageEvent),
    ).toMatchObject({ datasetId: "dataset-1", runningCount: 1 });

    expect(
      parseKnowledgeEvent("unsupported", {
        data: JSON.stringify({ dataset_id: "dataset-1" }),
      } as MessageEvent),
    ).toBeNull();
    expect(
      parseKnowledgeEvent("dataset_parsing_progress", {
        data: "not-json",
      } as MessageEvent),
    ).toBeNull();
  });

  test("merges live progress into only the matching dataset", () => {
    const next = applyKnowledgeEventToDatasets(DATASETS, {
      type: "dataset_parsing_progress",
      datasetId: "dataset-1",
      unstartCount: 1,
      runningCount: 1,
      cancelCount: 0,
      doneCount: 1,
      failCount: 0,
    });

    expect(next[0]).toMatchObject({
      id: "dataset-1",
      unstart_count: 1,
      running_count: 1,
      done_count: 1,
      fail_count: 0,
    });
    expect(next[1]).toBe(DATASETS[1]);
  });

  test("completed and failed events update terminal counters", () => {
    const completed = applyKnowledgeEventToDatasets(DATASETS, {
      type: "dataset_parsing_completed",
      datasetId: "dataset-1",
      doneCount: 3,
      failCount: 0,
    });
    expect(completed[0]).toMatchObject({
      running_count: 0,
      unstart_count: 0,
      done_count: 3,
      fail_count: 0,
    });

    const failed = applyKnowledgeEventToDatasets(completed, {
      type: "dataset_parsing_failed",
      datasetId: "dataset-1",
      failedDocuments: [{ id: "document-1", name: "broken.pdf" }],
    });
    expect(failed[0]).toMatchObject({ fail_count: 1, running_count: 0 });
  });
});
