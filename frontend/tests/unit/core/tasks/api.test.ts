import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import { fetchSubtaskSteps } from "@/core/tasks/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Error" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

function stepEvent(seq: number, messageIndex: number, toolName: string) {
  return {
    event_type: "subagent.step",
    seq,
    content: {
      task_id: "A",
      message_index: messageIndex,
      kind: "tool",
      text: "",
      tool_name: toolName,
    },
    metadata: { task_id: "A", message_index: messageIndex },
  };
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("fetchSubtaskSteps", () => {
  test("scopes the request to the task and only fetches subagent.step", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, []));

    await fetchSubtaskSteps("thread 1", "run/1", "task-A");

    const url = mockedFetch.mock.calls[0]![0] as string;
    expect(url).toContain(
      "/backend/api/threads/thread%201/runs/run%2F1/events",
    );
    expect(url).toContain("task_id=task-A");
    expect(url).toContain("event_types=subagent.step");
    expect(url).toContain("limit=");
    expect(url).not.toContain("after_seq");
  });

  test("pages forward with after_seq until a short page, accumulating in order", async () => {
    mockedFetch
      .mockResolvedValueOnce(
        jsonResponse(200, [
          stepEvent(10, 0, "web_search"),
          stepEvent(11, 1, "read_file"),
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(200, [stepEvent(12, 2, "bash")]));

    const steps = await fetchSubtaskSteps("t", "r", "A", 2);

    expect(steps.map((s) => s.message_index)).toEqual([0, 1, 2]);
    expect(steps.map((s) => s.tool_name)).toEqual([
      "web_search",
      "read_file",
      "bash",
    ]);
    expect(mockedFetch).toHaveBeenCalledTimes(2);
    expect(mockedFetch.mock.calls[0]![0] as string).not.toContain("after_seq");
    expect(mockedFetch.mock.calls[1]![0] as string).toContain("after_seq=11");
  });

  test("stops after a single page when it is shorter than the page size", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, [stepEvent(10, 0, "web_search")]),
    );

    const steps = await fetchSubtaskSteps("t", "r", "A", 500);

    expect(steps).toHaveLength(1);
    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  test("throws when a page request fails", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }));

    await expect(fetchSubtaskSteps("t", "r", "A")).rejects.toThrow();
  });
});
