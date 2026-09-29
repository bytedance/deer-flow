import { beforeEach, expect, rs, test } from "@rstest/core";

import { loadFrontendExtensions } from "@/core/extensions/registry";
import {
  bindFrontendServices,
  conversationText,
  latestVisibleAnswer,
  openConversation,
} from "@/core/extensions/services";
import type { AgentThread } from "@/core/threads/types";

const { request, getState, getThread } = rs.hoisted(() => ({
  request: rs.fn(),
  getState: rs.fn(),
  getThread: rs.fn(),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: request }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({ threads: { getState, get: getThread } }),
}));

beforeEach(() => {
  rs.clearAllMocks();
});

test("bookmark receives only the last visible assistant answer", async () => {
  const thread = {
    thread_id: "t",
    values: { title: "Example" },
  } as AgentThread;
  const answer = await latestVisibleAnswer({
    thread,
    messages: [
      { id: "a", type: "ai", content: "<think>SECRET</think>Visible answer" },
      {
        id: "h",
        type: "ai",
        content: "HIDDEN",
        additional_kwargs: { hide_from_ui: true },
      },
      { id: "u", type: "human", content: "Later question" },
    ],
  });
  expect(answer).toEqual({ id: "a", text: "Visible answer" });
});

const entry = {
  namespace: "community.stats",
  module: null,
  entry: null,
  title: "Stats",
  description: "",
  settings: { enabled: true },
  backend_actions: ["stats"],
};

test("backend-only entry stays visible without attempting a browser import", async () => {
  const importer = rs.fn();
  expect(await loadFrontendExtensions([entry], importer)).toEqual([entry]);
  expect(importer).not.toHaveBeenCalled();
});

test("backend bridge binds installed namespace and propagates administrator disable", async () => {
  const services = bindFrontendServices(
    {
      conversationText,
      showMessage: rs.fn(),
    },
    entry,
  );
  request.mockResolvedValue({
    ok: true,
    json: async () => ({ characters: 5 }),
  });
  expect(await services.callBackend("stats", { text: "hello" })).toEqual({
    characters: 5,
  });
  expect(request).toHaveBeenCalledWith(
    "/api/plugins/community.stats/actions/stats",
    expect.objectContaining({ method: "POST", body: '{"text":"hello"}' }),
  );
  await expect(services.callBackend("undeclared", {})).rejects.toThrow(
    "not declared",
  );
  expect(request).toHaveBeenCalledTimes(1);
  request.mockResolvedValue({ ok: false, status: 403 });
  await expect(services.callBackend("stats", {})).rejects.toThrow("403");
});

test("plugin transcript service shares visible-only sanitizer and authenticated sidebar read", async () => {
  const thread = {
    thread_id: "test",
    values: { title: "Synthetic" },
  } as AgentThread;
  const messages = [
    { id: "u", type: "human" as const, content: "hello" },
    {
      id: "a",
      type: "ai" as const,
      content: "<think>PRIVATE</think>world",
      additional_kwargs: { reasoning_content: "PRIVATE" },
    },
    {
      id: "hidden",
      type: "ai" as const,
      content: "HIDDEN",
      additional_kwargs: { hide_from_ui: true },
    },
  ];
  const text = await conversationText({ thread, messages });
  expect(text).toBe("hello\n\nworld");
  expect(getState).not.toHaveBeenCalled();
  getState.mockResolvedValue({ values: { messages } });
  expect(await conversationText({ thread })).toBe(text);
  expect(getState).toHaveBeenCalledWith("test");
  getState.mockRejectedValue(new Error("403"));
  await expect(conversationText({ thread })).rejects.toThrow("403");
});

for (const agent of [undefined, "researcher", "研究 / agent?#"]) {
  test(`plugin navigation resolves the current owner for ${agent ?? "default"} conversations`, async () => {
    getThread.mockResolvedValue({
      thread_id: "thread / 1",
      metadata: agent ? { agent_name: agent } : {},
    });
    const navigate = rs.fn();
    const signal = new AbortController().signal;
    await openConversation("thread / 1", navigate, signal);
    expect(getThread).toHaveBeenCalledWith("thread / 1", { signal });
    expect(navigate).toHaveBeenCalledWith(
      agent
        ? `/workspace/agents/${encodeURIComponent(agent)}/chats/thread%20%2F%201`
        : "/workspace/chats/thread%20%2F%201",
    );
  });
}

test("inaccessible conversations never fall back to the default agent route", async () => {
  const navigate = rs.fn();
  getThread.mockRejectedValue(new Error("403"));
  await expect(openConversation("thread", navigate)).rejects.toThrow("403");
  expect(navigate).not.toHaveBeenCalled();
});

test("unmounted or switched-account plugin pages cannot navigate after a late metadata read", async () => {
  const navigate = rs.fn();
  const abort = new AbortController();
  let finish!: (value: unknown) => void;
  getThread.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const pending = openConversation("thread", navigate, abort.signal);
  abort.abort();
  finish({ thread_id: "thread", metadata: { agent_name: "researcher" } });
  await expect(pending).rejects.toThrow();
  expect(navigate).not.toHaveBeenCalled();
  getThread.mockClear();
  await expect(
    openConversation("thread", navigate, abort.signal),
  ).rejects.toThrow();
  expect(getThread).not.toHaveBeenCalled();
});
