import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { toast } from "sonner";

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  exportThread: rs.fn<typeof exportThread>(),
  isMock: false,
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/threads/export", () => ({ exportThread: mocks.exportThread }));
rs.mock("sonner", () => ({ toast: { success: rs.fn(), error: rs.fn() } }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/components/workspace/tooltip", () => ({
  Tooltip: ({ children }: PropsWithChildren) => children,
}));
rs.mock("@/components/workspace/messages/context", () => ({
  useThread: () => ({
    isMock: mocks.isMock,
    thread: {
      messages: [latest],
      values: { title: "Long chat" },
      isLoading: false,
    },
  }),
}));

import { ExportTrigger } from "@/components/workspace/export-trigger";
import { enUS } from "@/core/i18n/locales/en-US";
import type { exportThread } from "@/core/threads/export";

const earliest = { id: "first", type: "human", content: "Original question" };
const latest = { id: "last", type: "ai", content: "Final answer" };
function page(messages: (typeof latest)[], start: number, next: number | null) {
  return Response.json({
    data: messages.map((content, i) => ({
      content,
      seq: start + i,
      run_id: `run-${start}`,
    })),
    has_more: next !== null,
    next_before_seq: next,
  });
}
async function selectExport(format = enUS.common.exportAsJSON) {
  render(<ExportTrigger threadId="chat" />);
  fireEvent.keyDown(screen.getByRole("button", { name: enUS.common.export }), {
    key: "Enter",
  });
  fireEvent.click(await screen.findByRole("menuitem", { name: format }));
}
beforeEach(() => {
  mocks.isMock = false;
  rs.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  cleanup();
  rs.resetAllMocks();
  rs.restoreAllMocks();
});

test.each([enUS.common.exportAsJSON, enUS.common.exportAsMarkdown])(
  "keeps a repeated human identity before both runs' answers for %s",
  async (format) => {
    mocks.fetch
      .mockResolvedValueOnce(
        page([{ ...earliest, content: "Updated question" }, latest], 100, 100),
      )
      .mockResolvedValueOnce(
        page([earliest, { ...latest, id: "answer-1" }], 1, null),
      );
    await selectExport(format);
    await waitFor(() => expect(mocks.exportThread).toHaveBeenCalledTimes(1));
    expect(mocks.exportThread.mock.calls[0]?.[1].map((m) => m.id)).toEqual([
      "first",
      "answer-1",
      "last",
    ]);
    expect(mocks.exportThread.mock.calls[0]?.[1][0]?.content).toBe(
      "Updated question",
    );
    expect(mocks.fetch.mock.calls[1]?.[0]).toContain("before_seq=100");
    for (const [url] of mocks.fetch.mock.calls) {
      expect(new URL(url, "http://localhost").searchParams.get("limit")).toBe(
        "200",
      );
    }
  },
);

test("does not download a partial transcript when an older page fails", async () => {
  mocks.fetch
    .mockResolvedValueOnce(page([latest], 100, 100))
    .mockResolvedValueOnce(new Response("Unavailable", { status: 503 }));
  await selectExport();
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(enUS.common.exportFailed),
  );
  expect(mocks.exportThread).not.toHaveBeenCalled();
  expect(toast.success).not.toHaveBeenCalled();
  expect(console.error).toHaveBeenCalledWith(expect.any(Error));
});

test("rejects a repeated cursor instead of looping forever", async () => {
  mocks.fetch.mockImplementation(async () => page([latest], 100, 100));
  await selectExport();
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(enUS.common.exportFailed),
  );
  expect(mocks.fetch).toHaveBeenCalledTimes(2);
  expect(mocks.exportThread).not.toHaveBeenCalled();
  expect(console.error).toHaveBeenCalledWith(expect.any(Error));
});

test("keeps public demo export local", async () => {
  mocks.isMock = true;
  await selectExport();
  await waitFor(() => expect(mocks.exportThread).toHaveBeenCalledTimes(1));
  expect(mocks.exportThread.mock.calls[0]?.[1]).toEqual([latest]);
  expect(mocks.fetch).not.toHaveBeenCalled();
});

test("disables export until history loading finishes", async () => {
  let finish!: (response: Response) => void;
  mocks.fetch.mockReturnValue(
    new Promise<Response>((resolve) => {
      finish = resolve;
    }),
  );
  await selectExport();
  const button = screen.getByRole("button", {
    name: enUS.common.export,
  });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(mocks.exportThread).not.toHaveBeenCalled();
  finish(page([latest], 100, null));
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  expect(mocks.exportThread).toHaveBeenCalledTimes(1);
});
