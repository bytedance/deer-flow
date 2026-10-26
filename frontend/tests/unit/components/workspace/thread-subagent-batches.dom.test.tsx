import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const featureState = rs.hoisted(() => ({
  repositoryAvailable: true,
  workerRunning: false,
}));
const batchState = rs.hoisted(() => ({
  batches: [] as Array<Record<string, unknown>>,
  control: rs.fn(),
  itemPages: [] as Array<Array<Record<string, unknown>>>,
  detailData: undefined as Record<string, unknown> | undefined,
  fetchNextPage: rs.fn(),
  hasNextPage: false,
}));

rs.mock("@/core/features", () => ({
  useSubagentBatchesCapability: () => ({
    ...featureState,
    maxRunning: 3,
    isLoading: false,
  }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: { loading: "Loading", loadMore: "Load more" },
      subagentBatches: {
        label: "Batches",
        title: "Subagent batches",
        description: "Durable batch work",
        workerUnavailable:
          "The batch worker is not running. Historical batches are read-only.",
        empty: "No batches",
        emptyHint: "Submit a batch",
        loadFailed: "Load failed",
        pause: "Pause",
        resume: "Resume",
        cancel: "Cancel",
        retryItem: "Retry",
        exportResults: "Export JSONL",
        viewResult: "Review result",
        resultTitle: "Batch result",
        resultDescription: "Stored report and captured evidence for this item.",
        report: "Report",
        evidence: "Captured evidence",
        noEvidence: "No captured evidence",
        acceptance: "Acceptance",
        noReport: "No report has been stored yet.",
        loadResultFailed: "Couldn't load batch result",
        truncated: "Report truncated",
        omittedEvidence: (count: number) => `${count} evidence entries omitted`,
        viewItems: "View items",
        hideItems: "Hide items",
        itemsFailed: "Items failed",
        progress: (completed: number, total: number) =>
          `${completed} of ${total}`,
        limits: (live: number, running: number) =>
          `Live ${live} running ${running}`,
        status: {
          queued: "Queued",
          running: "Running",
          paused: "Paused",
          completed: "Completed",
          failed: "Failed",
          cancelled: "Cancelled",
        },
      },
    },
  }),
}));

rs.mock("@/core/subagent-batches", () => ({
  completedSubagentBatchItems: () => 1,
  isActiveSubagentBatch: (batch: { status: string }) =>
    ["queued", "running", "paused"].includes(batch.status),
  subagentBatchProgress: () => 50,
  subagentBatchResultsUrl: () => "/results.jsonl",
  useSubagentBatchItemDetail: () => ({
    isLoading: false,
    isError: false,
    data: batchState.detailData,
  }),
  useControlSubagentBatch: () => ({
    isPending: false,
    variables: undefined,
    mutate: batchState.control,
  }),
  useRetrySubagentBatchItem: () => ({
    isPending: false,
    variables: undefined,
    mutate: rs.fn(),
  }),
  useSubagentBatchItems: () => ({
    data: { pages: batchState.itemPages },
    isLoading: false,
    isError: false,
    hasNextPage: batchState.hasNextPage,
    isFetchingNextPage: false,
    fetchNextPage: batchState.fetchNextPage,
  }),
  useSubagentBatches: () => ({
    data: batchState.batches,
    isLoading: false,
    isError: false,
  }),
}));

import { ThreadSubagentBatches } from "@/components/workspace/thread-subagent-batches";

const HISTORICAL_BATCH = {
  id: "batch-1",
  title: "Historical records",
  subagent_type: "general-purpose",
  status: "running",
  total_items: 2,
  max_live_items: 2,
  max_running_items: 1,
  max_attempts: 3,
  counts: {
    pending: 0,
    queued: 0,
    leased: 0,
    running: 1,
    succeeded: 1,
    failed: 0,
    cancelled: 0,
  },
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:01:00Z",
  completed_at: null,
};

afterEach(() => {
  cleanup();
  featureState.repositoryAvailable = true;
  featureState.workerRunning = false;
  batchState.batches = [];
  batchState.control.mockReset();
  batchState.itemPages = [];
  batchState.detailData = undefined;
  batchState.fetchNextPage.mockReset();
  batchState.hasNextPage = false;
});

describe("ThreadSubagentBatches capability gating", () => {
  it("keeps historical batches readable when the worker is stopped", async () => {
    batchState.batches = [HISTORICAL_BATCH];
    render(<ThreadSubagentBatches threadId="thread-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Batches" }));

    expect(
      await screen.findByText(
        "The batch worker is not running. Historical batches are read-only.",
      ),
    ).toBeDefined();
    expect(screen.getByRole("button", { name: "Pause" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(
      screen.getByRole("link", { name: "Export JSONL" }).getAttribute("href"),
    ).toBe("/results.jsonl");
  });

  it("hides an unused batch surface when neither worker nor history exists", () => {
    render(<ThreadSubagentBatches threadId="thread-1" />);
    expect(screen.queryByRole("button", { name: "Batches" })).toBeNull();
  });

  it("loads the next page of batch items", async () => {
    batchState.batches = [HISTORICAL_BATCH];
    batchState.itemPages = [
      [
        {
          id: "item-1",
          item_key: "record-1",
          position: 0,
          status: "succeeded",
          result_preview: "done",
        },
      ],
    ];
    batchState.hasNextPage = true;
    render(<ThreadSubagentBatches threadId="thread-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Batches" }));
    fireEvent.click(screen.getByRole("button", { name: "View items" }));
    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));

    expect(batchState.fetchNextPage).toHaveBeenCalledTimes(1);
  });

  it("reviews a stored report and captured evidence", async () => {
    batchState.batches = [HISTORICAL_BATCH];
    batchState.itemPages = [
      [
        {
          id: "item-1",
          item_key: "record-1",
          position: 0,
          status: "succeeded",
          result_preview: "preview",
        },
      ],
    ];
    batchState.detailData = {
      id: "item-1",
      item_key: "record-1",
      position: 0,
      status: "succeeded",
      attempt: 1,
      model_name: "model-a",
      report: "Stored report",
      report_truncated: false,
      error: null,
      stop_reason: null,
      acceptance_criteria: null,
      acceptance_verdict: null,
      evidence: {
        version: 1,
        omitted_count: 0,
        sources: [
          {
            id: "source-1",
            provider: "ragflow",
            dataset_id: "dataset-1",
            document_id: "document-1",
            chunk_id: "chunk-1",
            dataset_name: "Private KB",
            document_name: "report.md",
            text: "Captured excerpt",
            pages: [2],
            truncated: false,
          },
        ],
      },
      started_at: null,
      completed_at: null,
      updated_at: "2026-08-24T00:01:00Z",
    };
    render(<ThreadSubagentBatches threadId="thread-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Batches" }));
    fireEvent.click(screen.getByRole("button", { name: "View items" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Review result" }),
    );

    expect(await screen.findByText("Stored report")).toBeDefined();
    expect(screen.getByText("Captured excerpt")).toBeDefined();
  });
});
