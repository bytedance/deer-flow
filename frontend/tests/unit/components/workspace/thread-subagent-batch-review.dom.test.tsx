import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

const mocks = rs.hoisted(() => ({ fetch: rs.fn(), workerRunning: false }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/features", () => ({
  useSubagentBatchesCapability: () => ({
    repositoryAvailable: true,
    workerRunning: mocks.workerRunning,
    maxRunning: 3,
    isLoading: false,
  }),
}));

import { ThreadSubagentBatches } from "@/components/workspace/thread-subagent-batches";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type {
  SubagentBatch,
  SubagentBatchItem,
  SubagentBatchItemDetail,
} from "@/core/subagent-batches";
import { subagentBatchItemsKey } from "@/core/subagent-batches/hooks";

const translations = { "en-US": enUS, "zh-CN": zhCN };
const BATCH_URL = "/api/threads/thread-1/subagent-batches";
const DETAIL_URL = `${BATCH_URL}/batch-1/items/0`;
const SOURCE_ID = "0123456789abcdef0123456789abcdef-1";
const SECOND_SOURCE_ID = "0123456789abcdef0123456789abcdef-2";
const clients: QueryClient[] = [];
const noLocaleChange = () => undefined;
let detail: SubagentBatchItemDetail;
let compactItem: SubagentBatchItem;

const batch: SubagentBatch = {
  id: "batch-1",
  title: "Stored batch",
  subagent_type: "general-purpose",
  status: "running",
  total_items: 1,
  max_live_items: 1,
  max_running_items: 1,
  max_attempts: 3,
  counts: {
    pending: 0,
    queued: 0,
    leased: 0,
    running: 1,
    succeeded: 0,
    failed: 0,
    cancelled: 0,
  },
  created_at: "2026-10-17T00:00:00Z",
  updated_at: "2026-10-17T00:00:00Z",
  completed_at: null,
};
const item: SubagentBatchItem = {
  id: "item-1",
  batch_id: batch.id,
  item_key: "record-1",
  position: 0,
  status: "running",
  attempt: 1,
  model_name: "model-a",
  result_preview: null,
  result_truncated: false,
  error: null,
  stop_reason: null,
  token_usage: null,
  started_at: null,
  completed_at: null,
  created_at: batch.created_at,
  updated_at: batch.updated_at,
};

beforeEach(() => {
  mocks.workerRunning = false;
  compactItem = { ...item };
  detail = {
    ...item,
    status: "succeeded",
    report: "Stored report",
    report_truncated: false,
    acceptance_criteria: null,
    acceptance_verdict: null,
    evidence: {
      version: 1,
      omitted_count: 0,
      sources: [
        {
          id: SOURCE_ID,
          provider: "ragflow",
          dataset_id: "dataset-1",
          document_id: "document-1",
          chunk_id: "chunk-1",
          dataset_name: "Private KB",
          document_name: "shared.pdf",
          text: "First captured excerpt",
          pages: [2],
          truncated: false,
        },
      ],
    },
  };
  mocks.fetch.mockImplementation(async (input: string) => {
    const path = new URL(input, "http://test").pathname;
    const value =
      path === BATCH_URL
        ? [batch]
        : path === `${BATCH_URL}/batch-1/items`
          ? [compactItem]
          : path === DETAIL_URL
            ? detail
            : undefined;
    if (value === undefined)
      throw new Error(`Unexpected HTTP request: ${input}`);
    return new Response(JSON.stringify(value), {
      headers: { "Content-Type": "application/json" },
    });
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  mocks.fetch.mockReset();
});

async function openReview(locale: keyof typeof translations = "en-US") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <I18nContext.Provider
        value={{ locale, setLocale: noLocaleChange, t: translations[locale] }}
      >
        <ThreadSubagentBatches threadId="thread-1" />
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
  const t = translations[locale].subagentBatches;
  fireEvent.click(await screen.findByRole("button", { name: t.label }));
  fireEvent.click(await screen.findByRole("button", { name: t.viewItems }));
  expect(detailRequests()).toBe(0);
  fireEvent.click(await screen.findByRole("button", { name: t.viewResult }));
  await waitFor(() => expect(detailRequests()).toBe(1));
  return t;
}
function detailRequests() {
  return mocks.fetch.mock.calls.filter(
    ([input]) => String(input) === DETAIL_URL,
  ).length;
}

// Keep the component, query hooks, report renderer and citation dialogs real.
// Only the HTTP boundary and unrelated worker capability are replaced.
describe("stored batch result review", () => {
  it("refreshes an open terminal detail after an external retry and completion", async () => {
    compactItem = { ...item, status: "failed", error: "Previous failure" };
    detail = {
      ...detail,
      status: "failed",
      report: "Previous attempt",
      error: "Previous failure",
    };
    const t = await openReview();
    expect(await screen.findByText("Previous attempt")).toBeDefined();
    const client = clients[0]!;

    compactItem = {
      ...compactItem,
      status: "running",
      attempt: 2,
      updated_at: "2026-10-17T00:02:00Z",
      error: null,
    };
    detail = { ...detail, ...compactItem, report: null, evidence: null };
    await act(async () => {
      await client.refetchQueries({
        queryKey: subagentBatchItemsKey("thread-1", "batch-1"),
        exact: true,
      });
    });
    expect(await screen.findByText(t.noReport)).toBeDefined();
    expect(screen.queryByText("Previous attempt")).toBeNull();

    compactItem = {
      ...compactItem,
      status: "succeeded",
      updated_at: "2026-10-17T00:03:00Z",
      result_preview: "Retried report",
    };
    detail = { ...detail, ...compactItem, report: "**Retried report**" };
    await act(async () => {
      await client.refetchQueries({
        queryKey: subagentBatchItemsKey("thread-1", "batch-1"),
        exact: true,
      });
    });
    expect(
      await within(
        screen.getByRole("dialog", { name: t.resultTitle }),
      ).findByText("Retried report"),
    ).toBeDefined();
    const completedRequests = detailRequests();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2200));
    });
    expect(detailRequests()).toBe(completedRequests);
  }, 10000);

  it("refreshes an open running detail, then stops polling on its own terminal response", async () => {
    mocks.workerRunning = true;
    detail = { ...detail, status: "running", report: null, evidence: null };
    const t = await openReview();
    expect(await screen.findByText(t.noReport)).toBeDefined();
    detail = { ...detail, status: "succeeded", report: "**Completed report**" };
    await screen.findByText("Completed report", {}, { timeout: 5000 });
    // The compact list deliberately remains running; only the detail is terminal.
    const completedRequests = detailRequests();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2200));
    });
    expect(detailRequests()).toBe(completedRequests);
  }, 10000);

  it("stops polling a nonterminal detail when its dialog closes", async () => {
    detail = { ...detail, status: "running", report: null, evidence: null };
    const t = await openReview();
    expect(await screen.findByText(t.noReport)).toBeDefined();
    fireEvent.keyDown(screen.getByRole("dialog", { name: t.resultTitle }), {
      key: "Escape",
    });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: t.resultTitle })).toBeNull(),
    );
    const closedRequests = detailRequests();
    compactItem = {
      ...compactItem,
      attempt: 2,
      updated_at: "2026-10-17T00:02:00Z",
    };
    await act(async () => {
      await clients[0]!.refetchQueries({
        queryKey: subagentBatchItemsKey("thread-1", "batch-1"),
        exact: true,
      });
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2200));
    });
    expect(detailRequests()).toBe(closedRequests);
  });

  it("opens the matching stored excerpt for a report citation without fetching a provider", async () => {
    const first = detail.evidence!.sources[0]!;
    detail = {
      ...detail,
      report: `A cited claim [citation:2](#knowledge-${SECOND_SOURCE_ID}).`,
      evidence: {
        version: 1,
        omitted_count: 0,
        sources: [
          first,
          {
            ...first,
            id: SECOND_SOURCE_ID,
            chunk_id: "chunk-2",
            text: "Second captured excerpt <script>untrusted()</script>",
            pages: [7],
          },
        ],
      },
    };
    await openReview();
    fireEvent.click(
      await screen.findByRole("button", { name: "View source: shared.pdf" }),
    );
    const source = await screen.findByRole("dialog", { name: "shared.pdf" });
    expect(source.textContent).toContain(
      "Second captured excerpt <script>untrusted()</script>",
    );
    expect(source.textContent).not.toContain("First captured excerpt");
    expect(source.textContent).toContain("Pages 7");
    expect(source.querySelector("script")).toBeNull();
    expect(detailRequests()).toBe(1);
  });

  for (const locale of ["en-US", "zh-CN"] as const) {
    it(`shows omitted evidence even with no retained sources in ${locale}`, async () => {
      detail.evidence = { version: 1, sources: [], omitted_count: 3 };
      const t = await openReview(locale);
      expect(await screen.findByText(t.noEvidence)).toBeDefined();
      expect(screen.getByText(t.omittedEvidence(3))).toBeDefined();
    });
    it(`localizes the captured page label in ${locale}`, async () => {
      const t = await openReview(locale);
      expect(await screen.findByText(`${t.pagesLabel}: 2`)).toBeDefined();
    });
  }
});
