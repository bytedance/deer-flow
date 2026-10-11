import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const identity = rs.hoisted(() => ({ id: "alice" }));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: identity }),
}));
rs.mock("@/core/subagent-batches/api", () => ({
  fetchSubagentBatchResult: rs.fn(),
  retrySubagentBatchItem: rs.fn(),
}));

import { BatchItemReport } from "@/components/workspace/batch-item-report";
import { I18nProvider } from "@/core/i18n/context";
import {
  fetchSubagentBatchResult,
  retrySubagentBatchItem,
} from "@/core/subagent-batches/api";
import {
  subagentBatchResultKey,
  useRetrySubagentBatchItem,
} from "@/core/subagent-batches/hooks";
import type {
  SubagentBatchItem,
  SubagentBatchResult,
} from "@/core/subagent-batches/types";

const sourceId = "a".repeat(32) + "-1";
const saved: SubagentBatchResult = {
  id: "item",
  item_key: "Research",
  position: 0,
  status: "succeeded",
  attempt: 1,
  result_preview: "Preview",
  result_truncated: false,
  error: null,
  stop_reason: null,
  started_at: null,
  completed_at: null,
  updated_at: "now",
  acceptance_criteria: ["file:report.md exists"],
  acceptance_verdict: {
    all_hold: false,
    leaves: [
      {
        criterion: "file:report.md exists",
        checked: true,
        holds: false,
        detail: "Missing",
      },
    ],
  },
  result: `- ~~~\n  [citation:1](#knowledge-${sourceId})\n  ~~~\n\n[citation:2](#knowledge-${sourceId})\n\n<script>window.PWNED = true</script>`,
  evidence: {
    version: 1,
    omitted_count: 0,
    sources: [
      {
        id: sourceId,
        provider: "ragflow",
        dataset_name: "Original dataset",
        document_name: "Captured.pdf",
        text: "Original <script>unsafe</script>",
        pages: [3],
        truncated: false,
      },
    ],
  },
  revision: "first",
};
const item = {
  ...saved,
  batch_id: "batch",
  model_name: null,
  token_usage: null,
  created_at: "now",
} satisfies SubagentBatchItem;
const read = rs.mocked(fetchSubagentBatchResult);
let client: QueryClient;

beforeEach(() => {
  identity.id = "alice";
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  read.mockReset().mockResolvedValue(saved);
  rs.mocked(retrySubagentBatchItem).mockReset().mockResolvedValue(item);
});
afterEach(() => {
  cleanup();
  client.clear();
});

function App({
  position = 0,
  threadId = "thread",
  workerRunning = false,
  itemOverrides = {},
}: {
  position?: number;
  threadId?: string;
  workerRunning?: boolean;
  itemOverrides?: Partial<SubagentBatchItem>;
}) {
  return (
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale="en-US">
        <BatchItemReport
          threadId={threadId}
          batchId="batch"
          item={{ ...item, position, ...itemOverrides }}
          workerRunning={workerRunning}
        />
      </I18nProvider>
    </QueryClientProvider>
  );
}

for (const criteria of [null, []]) {
  it(`shows No criteria for an optional acceptance definition (${String(criteria)})`, async () => {
    read.mockResolvedValue({
      ...saved,
      acceptance_criteria: criteria,
      acceptance_verdict: null,
    });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "View report" }));
    const report = await screen.findByTestId("batch-saved-report");
    expect(report.textContent).toContain("No criteria");
    expect(report.textContent).not.toContain("Unverified");
  });
}

it("keeps a checker error Unverified when criteria exist", async () => {
  read.mockResolvedValue({ ...saved, acceptance_verdict: null });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  const report = await screen.findByTestId("batch-saved-report");
  expect(report.textContent).toContain("Unverified");
  expect(report.textContent).not.toContain("No criteria");
});

for (const status of ["pending", "queued", "leased", "running"] as const) {
  it(`waits for ${status} items without a preview before offering inspection`, async () => {
    const view = render(
      <App workerRunning itemOverrides={{ status, result_preview: null }} />,
    );
    expect(screen.queryByRole("button", { name: "View report" })).toBeNull();
    expect(read).not.toHaveBeenCalled();
    view.rerender(
      <App
        workerRunning
        itemOverrides={{ status: "succeeded", result_preview: null }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "View report" }));
    await screen.findByTestId("batch-saved-report");
    expect(read).toHaveBeenCalledTimes(1);
  });
}

for (const status of ["succeeded", "failed", "cancelled"] as const) {
  it(`allows inspection of a terminal ${status} item without a preview`, () => {
    render(<App itemOverrides={{ status, result_preview: null }} />);
    expect(screen.getByRole("button", { name: "View report" })).toBeDefined();
  });
}

it("allows a running item's saved preview to be inspected", async () => {
  render(<App workerRunning itemOverrides={{ status: "running" }} />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  await screen.findByTestId("batch-saved-report");
  expect(read).toHaveBeenCalledTimes(1);
});

it("resolves saved output links through the current thread artifact route", async () => {
  read.mockResolvedValue({
    ...saved,
    result: "[Report](/mnt/user-data/outputs/report.md)",
  });
  const view = render(<App threadId="original-thread" />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  const report = await screen.findByRole("link", { name: "Report" });
  expect(report.getAttribute("href")).toBe(
    "/api/threads/original-thread/artifacts/mnt/user-data/outputs/report.md",
  );
  expect(report.getAttribute("target")).toBe("_blank");
  expect(report.getAttribute("rel")).toBe("noopener noreferrer");
  view.rerender(<App threadId="next-thread" />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  const next = await screen.findByRole("link", { name: "Report" });
  expect(next.getAttribute("href")).toBe(
    "/api/threads/next-thread/artifacts/mnt/user-data/outputs/report.md",
  );
});

it("resolves saved output images without borrowing the conversation's artifact list", async () => {
  read.mockResolvedValue({
    ...saved,
    result:
      "![Chart](/mnt/user-data/outputs/chart%20final.png?v=2#detail)\n\n![Remote](https://example.com/chart.png)\n\n![Relative](chart.png)",
  });
  const view = render(<App threadId="original-thread" />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  const chart = await screen.findByRole("img", { name: "Chart" });
  const original =
    "/api/threads/original-thread/artifacts/mnt/user-data/outputs/chart%20final.png?v=2#detail";
  expect(chart.getAttribute("src")).toBe(original);
  expect(chart.closest("a")?.getAttribute("href")).toBe(original);
  expect(screen.getByRole("img", { name: "Remote" }).getAttribute("src")).toBe(
    "https://example.com/chart.png",
  );
  expect(
    screen.getByRole("img", { name: "Relative" }).getAttribute("src"),
  ).toBe("chart.png");
  view.rerender(<App threadId="next-thread" />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  const next = await screen.findByRole("img", { name: "Chart" });
  expect(next.getAttribute("src")).toBe(
    original.replace("original-thread", "next-thread"),
  );
});

it("reads on demand and uses native Markdown for a list-contained tilde fence", async () => {
  render(<App />);
  expect(read).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  const report = await screen.findByTestId("batch-saved-report");
  expect(report.textContent).toContain("succeeded");
  expect(report.textContent).toContain("Unmet");
  expect(report.textContent).toContain("Missing");
  expect(report.querySelector("code")?.textContent).toContain("[citation:1]");
  expect(report.querySelector("script")).toBeNull();
  const citations = screen.getAllByRole("button", {
    name: "View source: Captured.pdf",
  });
  expect(citations.length).toBe(1);
  expect(citations[0]!.textContent).toContain("2");
  fireEvent.click(citations[0]!);
  const dialogs = screen.getAllByRole("dialog", { hidden: true });
  expect(dialogs.at(-1)?.textContent).toContain(
    "Original <script>unsafe</script>",
  );
  expect(dialogs.at(-1)?.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByTestId("batch-saved-report")).toBeDefined();
});

it("cancels a pending read when the report closes and rereads on reopening", async () => {
  let signal: AbortSignal | undefined;
  read.mockImplementationOnce((_thread, _batch, _position, current) => {
    signal = current;
    return new Promise(() => undefined);
  });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() => expect(signal?.aborted).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  await screen.findByTestId("batch-saved-report");
  expect(read).toHaveBeenCalledTimes(2);
});

it("discards the report and nested source dialog on a principal or item switch", async () => {
  const view = render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "View source: Captured.pdf" }),
  );
  identity.id = "bob";
  view.rerender(<App />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByText("Original <script>unsafe</script>")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  await screen.findByTestId("batch-saved-report");
  expect(
    client.getQueryData(subagentBatchResultKey("thread", "batch", 0, "bob")),
  ).toEqual(saved);
  view.rerender(<App position={1} />);
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("keeps a legacy pending item unverified and reports absent or truncated content", async () => {
  read.mockResolvedValue({
    ...saved,
    status: "pending",
    result: null,
    evidence: null,
    acceptance_verdict: null,
    result_truncated: true,
  });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  const report = await screen.findByTestId("batch-saved-report");
  expect(report.textContent).toContain("Unverified");
  expect(report.textContent).toContain("No report saved");
  expect(report.textContent).toContain("truncated");
  expect(
    screen.queryByRole("button", { name: "View source: Captured.pdf" }),
  ).toBeNull();
});

it("shows a read failure and allows a fresh retry", async () => {
  read.mockRejectedValueOnce(new Error("Not found"));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Not found");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByTestId("batch-saved-report");
});

it("cancels a previous thread read and ignores its late completion", async () => {
  let complete: (result: SubagentBatchResult) => void = () => undefined;
  let signal: AbortSignal | undefined;
  read.mockImplementationOnce((_thread, _batch, _position, current) => {
    signal = current;
    return new Promise((resolve) => {
      complete = resolve;
    });
  });
  const view = render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
  view.rerender(<App threadId="other-thread" />);
  await waitFor(() => expect(signal?.aborted).toBe(true));
  await act(async () => {
    complete(saved);
  });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    client.getQueryData(
      subagentBatchResultKey("other-thread", "batch", 0, "alice"),
    ),
  ).toBeUndefined();
});

it("closes an obsolete source when the same attempt receives a new revision", async () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "View source: Captured.pdf" }),
  );
  await act(async () => {
    client.setQueryData(subagentBatchResultKey("thread", "batch", 0, "alice"), {
      ...saved,
      revision: "second",
      evidence: null,
    });
  });
  await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
  expect(screen.queryByText("Original <script>unsafe</script>")).toBeNull();
  expect(screen.getByTestId("batch-saved-report")).toBeDefined();
});

it("renders the native million-character ceiling and preserves its truncated notice", async () => {
  read.mockResolvedValue({
    ...saved,
    result: "x".repeat(999_990) + "REPORT_END",
    result_truncated: true,
    evidence: null,
  });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  const report = await screen.findByTestId("batch-saved-report");
  expect(report.textContent).toContain("REPORT_END");
  expect(report.textContent).toContain("This saved report was truncated.");
});

it("polls a running worker's pending result and stops after terminal completion", async () => {
  read.mockResolvedValueOnce({
    ...saved,
    status: "pending",
    result: null,
    evidence: null,
    acceptance_verdict: null,
  });
  render(<App workerRunning />);
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  await waitFor(() =>
    expect(screen.getByTestId("batch-saved-report").textContent).toContain(
      "pending",
    ),
  );
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2), { timeout: 3000 });
  await waitFor(() =>
    expect(screen.getByTestId("batch-saved-report").textContent).toContain(
      "succeeded",
    ),
  );
  await new Promise((resolve) => setTimeout(resolve, 2200));
  expect(read).toHaveBeenCalledTimes(2);
});

it("invalidates an open report after retry and reads the cleared new attempt", async () => {
  let retry: () => void = () => undefined;
  function RetryControl() {
    const mutation = useRetrySubagentBatchItem("thread", "batch");
    retry = () => mutation.mutate("item");
    return null;
  }
  read
    .mockResolvedValueOnce({
      ...saved,
      status: "failed",
      result: "Old partial",
      evidence: null,
    })
    .mockResolvedValue({
      ...saved,
      status: "pending",
      result: null,
      evidence: null,
      attempt: 2,
      revision: "retried",
    });
  render(
    <QueryClientProvider client={client}>
      <RetryControl />
      <App />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "View report" }));
  await waitFor(() =>
    expect(screen.getByTestId("batch-saved-report").textContent).toContain(
      "Old partial",
    ),
  );
  await act(async () => {
    retry();
  });
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(screen.getByTestId("batch-saved-report").textContent).not.toContain(
      "Old partial",
    ),
  );
  expect(
    client.getQueryData<SubagentBatchResult>(
      subagentBatchResultKey("thread", "batch", 0, "alice"),
    )?.attempt,
  ).toBe(2);
  expect(rs.mocked(retrySubagentBatchItem)).toHaveBeenCalledWith(
    "thread",
    "batch",
    "item",
  );
});
