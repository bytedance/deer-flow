/**
 * Shared mock helpers for E2E tests.
 *
 * Intercepts all LangGraph / Backend API endpoints so tests can run without
 * a real backend.  Each test file imports `mockLangGraphAPI` and
 * `handleRunStream` from here.
 */

import type { Page, Route } from "@playwright/test";

// ---------------------------------------------------------------------------
// Constants — deterministic IDs used across tests
// ---------------------------------------------------------------------------

export const MOCK_THREAD_ID = "00000000-0000-0000-0000-000000000001";
export const MOCK_THREAD_ID_2 = "00000000-0000-0000-0000-000000000002";
export const MOCK_RUN_ID = "00000000-0000-0000-0000-000000000099";

const MOCK_AUTH_USER = {
  id: "default",
  email: "default@test.local",
  system_role: "admin",
  needs_setup: false,
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MockThread = {
  thread_id: string;
  title?: string;
  updated_at?: string;
  agent_name?: string;
  metadata?: Record<string, unknown>;
  messages?: unknown[];
  artifacts?: string[];
  goal?: Record<string, unknown> | null;
};

export type MockAgent = {
  name: string;
  description?: string;
  system_prompt?: string;
};

export type MockSkill = {
  name: string;
  description: string;
  category?: string;
  license?: string | null;
  enabled?: boolean;
};

export type MockAPIOptions = {
  threads?: MockThread[];
  agents?: MockAgent[];
  skills?: MockSkill[];
  scheduledTasks?: Array<{
    id: string;
    thread_id: string | null;
    context_mode?: "fresh_thread_per_run" | "reuse_thread";
    last_thread_id?: string | null;
    title: string;
    prompt: string;
    schedule_type: "once" | "cron";
    schedule_spec: Record<string, unknown>;
    timezone: string;
    status:
      | "enabled"
      | "paused"
      | "running"
      | "completed"
      | "failed"
      | "cancelled";
    next_run_at: string | null;
    last_run_at: string | null;
    last_run_id: string | null;
    last_error: string | null;
    run_count: number;
    created_at: string;
    updated_at: string;
  }>;
  uploadLimits?: {
    max_files: number;
    max_file_size: number;
    max_total_size: number;
  };
};

const DEFAULT_SKILLS: MockSkill[] = [
  {
    name: "data-analysis",
    description: "Analyze structured data and produce charts.",
    category: "public",
    enabled: true,
  },
  {
    name: "frontend-design",
    description: "Create polished frontend interfaces.",
    category: "public",
    enabled: true,
  },
  {
    name: "disabled-skill",
    description: "Hidden from slash autocomplete.",
    category: "public",
    enabled: false,
  },
];

function mockStreamMessages() {
  return [
    {
      type: "human",
      id: "msg-human-1",
      content: [{ type: "text", text: "Hello" }],
    },
    {
      type: "ai",
      id: "msg-ai-1",
      content: "Hello from DeerFlow!",
    },
  ];
}

// ---------------------------------------------------------------------------
// mockLangGraphAPI
// ---------------------------------------------------------------------------

/**
 * Mock all LangGraph API endpoints that the frontend calls on page load and
 * during message sending.  Without these mocks the pages would hang waiting
 * for a real backend.
 */
export function mockLangGraphAPI(page: Page, options?: MockAPIOptions) {
  let threads = [...(options?.threads ?? [])];
  const agents = options?.agents ?? [];
  const skills = options?.skills ?? DEFAULT_SKILLS;
  const scheduledTasks = options?.scheduledTasks ?? [];
  let mutableScheduledTasks = [...scheduledTasks];
  const mutableTaskRuns: Record<
    string,
    Array<{
      id: string;
      task_id: string;
      thread_id: string | null;
      run_id: string | null;
      scheduled_for: string;
      trigger: "scheduled" | "manual";
      status: "queued" | "running" | "success" | "failed" | "skipped";
      error: string | null;
      started_at: string | null;
      finished_at: string | null;
      created_at: string;
    }>
  > = {};
  const uploadLimits = options?.uploadLimits ?? {
    max_files: 10,
    max_file_size: 50 * 1024 * 1024,
    max_total_size: 100 * 1024 * 1024,
  };

  const upsertThread = (thread: MockThread) => {
    threads = [
      thread,
      ...threads.filter((existing) => existing.thread_id !== thread.thread_id),
    ];
  };

  const threadSearchResult = (thread: MockThread) => ({
    thread_id: thread.thread_id,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: thread.updated_at ?? "2025-01-01T00:00:00Z",
    metadata: {
      ...(thread.metadata ?? {}),
      ...(thread.agent_name ? { agent_name: thread.agent_name } : {}),
    },
    status: "idle",
    values: { title: thread.title ?? "Untitled", goal: thread.goal ?? null },
  });

  // Auth — keep workspace tests independent from a real gateway session.
  void page.route("**/api/v1/auth/me", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_AUTH_USER),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/v1/auth/setup-status", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ needs_setup: false }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/v1/auth/logout", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 204 });
    }
    return route.fallback();
  });

  void page.route("**/api/channels/providers", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false, providers: [] }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/channels/connections", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ connections: [] }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/suggestions/config", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/scheduled-tasks", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          mutableScheduledTasks.map((task) => ({
            context_mode: "fresh_thread_per_run",
            last_thread_id: null,
            ...task,
            thread_id: task.thread_id ?? null,
          })),
        ),
      });
    }
    if (route.request().method() === "POST") {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      const threadId =
        typeof payload.thread_id === "string" ? payload.thread_id : "";
      const title = typeof payload.title === "string" ? payload.title : "";
      const prompt = typeof payload.prompt === "string" ? payload.prompt : "";
      const timezone =
        typeof payload.timezone === "string" ? payload.timezone : "UTC";
      const created = {
        id: "task-created",
        thread_id: threadId || null,
        context_mode:
          (payload.context_mode as "fresh_thread_per_run" | "reuse_thread") ??
          "fresh_thread_per_run",
        last_thread_id: null,
        title,
        prompt,
        schedule_type: payload.schedule_type as "once" | "cron",
        schedule_spec: (payload.schedule_spec as Record<string, unknown>) ?? {},
        timezone,
        status: "enabled" as const,
        next_run_at: null,
        last_run_at: null,
        last_run_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-07-01T00:00:00+00:00",
        updated_at: "2026-07-01T00:00:00+00:00",
      };
      mutableScheduledTasks = [created, ...mutableScheduledTasks];
      mutableTaskRuns[created.id] = [];
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(created),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/scheduled-tasks/*/pause", (route) => {
    if (route.request().method() === "POST") {
      const taskId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
      );
      mutableScheduledTasks = mutableScheduledTasks.map((task) =>
        task.id === taskId ? { ...task, status: "paused" as const } : task,
      );
      const task = mutableScheduledTasks.find((item) => item.id === taskId);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(task),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/scheduled-tasks/*/resume", (route) => {
    if (route.request().method() === "POST") {
      const taskId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
      );
      mutableScheduledTasks = mutableScheduledTasks.map((task) =>
        task.id === taskId ? { ...task, status: "enabled" as const } : task,
      );
      const task = mutableScheduledTasks.find((item) => item.id === taskId);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(task),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/scheduled-tasks/*/trigger", (route) => {
    if (route.request().method() === "POST") {
      const taskId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
      );
      const task = mutableScheduledTasks.find((item) => item.id === taskId);
      if (task) {
        const runId = `run-${taskId}`;
        mutableTaskRuns[taskId] = [
          {
            id: `task-run-${taskId}`,
            task_id: taskId,
            thread_id: task.thread_id,
            run_id: runId,
            scheduled_for: "2026-07-01T00:00:00+00:00",
            trigger: "manual",
            status: "success",
            error: null,
            started_at: "2026-07-01T00:00:00+00:00",
            finished_at: "2026-07-01T00:00:00+00:00",
            created_at: "2026-07-01T00:00:00+00:00",
          },
          ...(mutableTaskRuns[taskId] ?? []),
        ];
        mutableScheduledTasks = mutableScheduledTasks.map((item) =>
          item.id === taskId
            ? {
                ...item,
                last_run_id: runId,
                last_run_at: "2026-07-01T00:00:00+00:00",
                run_count: item.run_count + 1,
              }
            : item,
        );
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: taskId, triggered: true }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/scheduled-tasks/*", (route) => {
    const request = route.request();
    if (request.method() === "PATCH") {
      const taskId = decodeURIComponent(
        new URL(request.url()).pathname.split("/").at(-1) ?? "",
      );
      const payload = request.postDataJSON() as Record<string, unknown>;
      let updated: (typeof mutableScheduledTasks)[number] | undefined;
      mutableScheduledTasks = mutableScheduledTasks.map((task) => {
        if (task.id !== taskId) {
          return task;
        }
        updated = {
          ...task,
          ...(typeof payload.title === "string"
            ? { title: payload.title }
            : {}),
          ...(typeof payload.prompt === "string"
            ? { prompt: payload.prompt }
            : {}),
          ...(payload.schedule_spec
            ? {
                schedule_spec: payload.schedule_spec as Record<string, unknown>,
              }
            : {}),
          ...(typeof payload.timezone === "string"
            ? { timezone: payload.timezone }
            : {}),
          updated_at: "2026-07-01T00:00:00+00:00",
        };
        return updated;
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updated ?? {}),
      });
    }
    if (request.method() === "DELETE") {
      const taskId = decodeURIComponent(
        new URL(request.url()).pathname.split("/").at(-1) ?? "",
      );
      mutableScheduledTasks = mutableScheduledTasks.filter(
        (task) => task.id !== taskId,
      );
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: taskId, deleted: true }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/threads/*/scheduled-tasks", (route) => {
    if (route.request().method() === "GET") {
      const url = new URL(route.request().url());
      const parts = url.pathname.split("/");
      const threadId = decodeURIComponent(
        parts[parts.indexOf("threads") + 1] ?? "",
      );
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          mutableScheduledTasks
            .filter((task) => task.thread_id === threadId)
            .map((task) => ({
              context_mode: "fresh_thread_per_run",
              last_thread_id: null,
              ...task,
              thread_id: task.thread_id ?? null,
            })),
        ),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/scheduled-tasks/*/runs", (route) => {
    if (route.request().method() === "GET") {
      const taskId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
      );
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mutableTaskRuns[taskId] ?? []),
      });
    }
    return route.fallback();
  });

  // Thread search — sidebar thread list & chats list page
  void page.route("**/api/langgraph/threads/search", async (route) => {
    const body = threads.map(threadSearchResult);

    let limit: number | undefined;
    let offset = 0;
    try {
      const postData = route.request().postDataJSON() as {
        limit?: number;
        offset?: number;
      } | null;
      if (postData) {
        if (typeof postData.limit === "number") {
          limit = postData.limit;
        }
        if (typeof postData.offset === "number") {
          offset = postData.offset;
        }
      }
    } catch {
      // No / invalid JSON body — fall back to returning the full list.
    }

    const sliced =
      typeof limit === "number" ? body.slice(offset, offset + limit) : body;

    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(sliced),
    });
  });

  // Thread create — called when user sends first message in a new chat
  void page.route("**/api/langgraph/threads", (route) => {
    if (route.request().method() === "POST") {
      upsertThread({
        thread_id: MOCK_THREAD_ID,
        title: "New Chat",
        updated_at: new Date().toISOString(),
        messages: mockStreamMessages(),
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          thread_id: MOCK_THREAD_ID,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          metadata: {},
          status: "idle",
          values: {},
        }),
      });
    }
    return route.fallback();
  });

  // Thread update (PATCH) — metadata update after creation
  void page.route("**/api/langgraph/threads/*", (route) => {
    const threadId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-1) ?? "",
    );
    const matchingThread = threads.find(
      (thread) => thread.thread_id === threadId,
    );
    if (route.request().method() === "GET") {
      if (!matchingThread) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Thread not found" }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(threadSearchResult(matchingThread)),
      });
    }
    if (route.request().method() === "PATCH") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ thread_id: MOCK_THREAD_ID }),
      });
    }
    if (route.request().method() === "DELETE") {
      threads = threads.filter((thread) => thread.thread_id !== threadId);
      return route.fulfill({
        status: 204,
      });
    }
    return route.fallback();
  });

  void page.route(/\/api\/threads\/[^/]+$/, (route) => {
    if (route.request().method() === "DELETE") {
      return route.fulfill({
        status: 204,
      });
    }
    return route.fallback();
  });

  void page.route(/\/api\/threads\/[^/]+\/goal$/, async (route) => {
    const threadId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
    );
    let matchingThread = threads.find(
      (thread) => thread.thread_id === threadId,
    );

    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ goal: matchingThread?.goal ?? null }),
      });
    }

    if (route.request().method() === "DELETE") {
      if (matchingThread) {
        matchingThread.goal = null;
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ goal: null }),
      });
    }

    if (route.request().method() === "PUT") {
      const payload = route.request().postDataJSON() as {
        objective?: string;
      };
      const goal = {
        objective: payload.objective ?? "",
        status: "active",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        continuation_count: 0,
        max_continuations: 8,
        no_progress_count: 0,
        max_no_progress_continuations: 2,
      };
      matchingThread ??= {
        thread_id: threadId,
        title: "New Chat",
        updated_at: new Date().toISOString(),
      };
      upsertThread({ ...matchingThread, goal });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ goal }),
      });
    }

    return route.fallback();
  });

  void page.route("**/api/threads/*/uploads/limits", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(uploadLimits),
      });
    }
    return route.fallback();
  });

  // Thread history — useStream fetches state history on mount
  void page.route("**/api/langgraph/threads/*/history", (route) => {
    const url = route.request().url();

    // For threads that exist in our mock data, return history with messages
    const matchingThread = threads.find((t) => url.includes(t.thread_id));
    if (matchingThread) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            values: {
              title: matchingThread.title ?? "Untitled",
              goal: matchingThread.goal ?? null,
              messages: matchingThread.messages ?? [
                {
                  type: "human",
                  id: `msg-human-${matchingThread.thread_id}`,
                  content: [{ type: "text", text: "Previous question" }],
                },
                {
                  type: "ai",
                  id: `msg-ai-${matchingThread.thread_id}`,
                  content: `Response in thread ${matchingThread.title ?? matchingThread.thread_id}`,
                },
              ],
              artifacts: matchingThread.artifacts ?? [],
            },
            next: [],
            metadata: {},
            created_at: "2025-01-01T00:00:00Z",
            parent_config: null,
          },
        ]),
      });
    }

    // New threads — empty history
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "[]",
    });
  });

  // Thread state — getState for individual thread
  void page.route("**/api/langgraph/threads/*/state", (route) => {
    if (route.request().method() === "GET") {
      const url = route.request().url();
      const matchingThread = threads.find((t) => url.includes(t.thread_id));
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          values: {
            title: matchingThread?.title ?? "Untitled",
            goal: matchingThread?.goal ?? null,
            messages: matchingThread
              ? (matchingThread.messages ?? [
                  {
                    type: "human",
                    id: `msg-human-${matchingThread.thread_id}`,
                    content: [{ type: "text", text: "Previous question" }],
                  },
                  {
                    type: "ai",
                    id: `msg-ai-${matchingThread.thread_id}`,
                    content: `Response in thread ${matchingThread.title ?? matchingThread.thread_id}`,
                  },
                ])
              : [],
            artifacts: matchingThread?.artifacts ?? [],
          },
          next: [],
          metadata: {},
          created_at: "2025-01-01T00:00:00Z",
        }),
      });
    }
    return route.fallback();
  });

  // The URL carries a query string (e.g. `?limit=10&offset=0`), which Playwright
  // glob `*` does NOT cross, so we match with a regex anchored to `/runs`
  // followed by `?` or end-of-string.  This must NOT match `/runs/stream`.
  void page.route(/\/api\/langgraph\/threads\/[^/]+\/runs(\?|$)/, (route) => {
    if (route.request().method() === "GET") {
      const url = route.request().url();
      const matchingThread = threads.find((t) => url.includes(t.thread_id));
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          matchingThread
            ? [
                {
                  run_id: `run-${matchingThread.thread_id}`,
                  thread_id: matchingThread.thread_id,
                  assistant_id: "lead_agent",
                  status: "success",
                  metadata: {},
                  kwargs: {},
                  created_at: "2025-01-01T00:00:00Z",
                  updated_at:
                    matchingThread.updated_at ?? "2025-01-01T00:00:00Z",
                },
              ]
            : [],
        ),
      });
    }
    return route.fallback();
  });

  void page.route(
    /\/api\/threads\/([^/]+)\/runs\/([^/]+)\/messages/,
    (route) => {
      if (route.request().method() === "GET") {
        const url = route.request().url();
        const matchingThread = threads.find((t) =>
          url.includes(`/api/threads/${t.thread_id}/runs/`),
        );
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: (matchingThread?.messages ?? []).map((message, index) => ({
              run_id: `run-${matchingThread?.thread_id ?? "unknown"}`,
              content: message,
              metadata: { caller: "lead_agent" },
              created_at: `2025-01-01T00:00:${String(index).padStart(2, "0")}Z`,
            })),
            hasMore: false,
          }),
        });
      }
      return route.fallback();
    },
  );

  // Run stream — returns a minimal SSE response with an AI message
  const handleMockRunStream = (route: Route) => {
    const requestUrl = route.request().url();
    const matchingThread = threads.find((thread) =>
      requestUrl.includes(encodeURIComponent(thread.thread_id)),
    );
    const fallbackGoal = threads.find((thread) => thread.goal)?.goal ?? null;
    const goal = matchingThread?.goal ?? fallbackGoal;
    upsertThread({
      thread_id: MOCK_THREAD_ID,
      title: "New Chat",
      updated_at: new Date().toISOString(),
      goal,
      messages: mockStreamMessages(),
    });
    return handleRunStream(route, { goal });
  };

  void page.route("**/api/langgraph/runs/stream", handleMockRunStream);
  void page.route(
    "**/api/langgraph/threads/*/runs/stream",
    handleMockRunStream,
  );

  // Models list — model picker dropdown
  void page.route("**/api/models", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          models: [],
          token_usage: { enabled: false },
        }),
      });
    }
    return route.fallback();
  });

  // Feature flags — frontend gates UI (e.g. agents) on these. Default to
  // enabled so existing tests exercise the normal path; tests that need the
  // disabled state override this route after calling mockLangGraphAPI.
  void page.route("**/api/features", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ agents_api: { enabled: true } }),
      });
    }
    return route.fallback();
  });

  // Skills list — settings page and slash autocomplete
  void page.route("**/api/skills", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ skills }),
      });
    }
    return route.fallback();
  });

  // Follow-up suggestions — input box auto-suggest after AI response
  void page.route("**/api/threads/*/suggestions", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ suggestions: [] }),
      });
    }
    return route.fallback();
  });

  // Agents list — sidebar & gallery page
  void page.route("**/api/agents", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ agents }),
      });
    }
    return route.fallback();
  });

  // Individual agent — agent chat page
  void page.route("**/api/agents/*", (route) => {
    if (route.request().method() === "GET") {
      const url = route.request().url();
      const agent = agents.find((a) => url.endsWith(`/api/agents/${a.name}`));
      if (agent) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(agent),
        });
      }
    }
    return route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Agent not found" }),
    });
  });
}

// ---------------------------------------------------------------------------
// handleRunStream
// ---------------------------------------------------------------------------

/**
 * Build a minimal SSE stream that the LangGraph SDK can parse.
 * The stream returns a single AI message: "Hello from DeerFlow!".
 */
export function handleRunStream(
  route: Route,
  values: Record<string, unknown> = {},
) {
  const events = [
    {
      event: "metadata",
      data: { run_id: MOCK_RUN_ID, thread_id: MOCK_THREAD_ID },
    },
    {
      event: "values",
      data: {
        ...values,
        messages: mockStreamMessages(),
      },
    },
    { event: "end", data: {} },
  ];

  const body = events
    .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
    .join("");

  return route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body,
  });
}
