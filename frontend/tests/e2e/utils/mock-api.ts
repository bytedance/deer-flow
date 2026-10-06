/**
 * Shared mock helpers for E2E tests.
 *
 * Intercepts all LangGraph / Backend API endpoints so tests can run without
 * a real backend.  Each test file imports `mockLangGraphAPI` and
 * `handleRunStream` from here.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import type { Page, Route } from "@playwright/test";

// ---------------------------------------------------------------------------
// Constants — deterministic IDs used across tests
// ---------------------------------------------------------------------------

export const MOCK_THREAD_ID = "00000000-0000-0000-0000-000000000001";
export const MOCK_THREAD_ID_2 = "00000000-0000-0000-0000-000000000002";
export const MOCK_SIDECAR_THREAD_ID = "00000000-0000-0000-0000-0000000000aa";
export const MOCK_RUN_ID = "00000000-0000-0000-0000-000000000099";
// Keep in sync with frontend runtime thread utils and the backend thread_meta
// constant; the mock must mirror the same metadata contract for pin ordering.
export const THREAD_PINNED_METADATA_KEY = "deerflow_pinned";

// Keep in sync with frontend runtime thread utils and the backend thread_meta
// constant; the mock must mirror the same metadata contract for project
// membership.
export const THREAD_PROJECT_METADATA_KEY = "deerflow_project_id";

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
  /** Thread search `unread` (a server-originated run changed since it was opened); default false. */
  unread?: boolean;
};

export type MockProject = {
  id: string;
  name: string;
  instructions?: string;
  presentation?: Record<string, unknown>;
  status?: "active" | "archived";
  created_at?: string;
  updated_at?: string;
};

export type MockProjectDocument = {
  id: string;
  project_id: string;
  name: string;
  size_bytes: number;
  sha256?: string;
  content_missing?: boolean;
  source_thread_id?: string | null;
  source_kind?: "upload" | "output" | null;
  source_name?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type MockTrashDocument = MockProjectDocument & {
  trashed_at: string;
  trash_origin?: { project_id: string; project_name: string } | null;
};

export type MockThreadFileGroup = {
  thread_id: string;
  display_name: string;
  updated_at: string;
  files: Array<{
    kind: "upload" | "output";
    name: string;
    size_bytes: number;
    modified_at: string;
    artifact_url: string;
  }>;
  truncated?: boolean;
};

export type MockAgent = {
  name: string;
  display_name?: string | null;
  description?: string;
  system_prompt?: string;
  tool_groups?: string[] | null;
  skills?: string[] | null;
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
  projects?: MockProject[];
  projectsConfig?: {
    instructions_max_bytes?: number;
    trash_retention_days?: number;
  };
  projectDocuments?: MockProjectDocument[];
  trashDocuments?: MockTrashDocument[];
  threadFileGroups?: MockThreadFileGroup[];
  createdThreadMessages?: unknown[];
  honorRequestedThreadId?: boolean;
  agents?: MockAgent[];
  skills?: MockSkill[];
  scheduledTasks?: MockScheduledTask[];
  /** Initial run history per task id (newest first), served by the runs route. */
  scheduledTaskRuns?: Record<string, MockScheduledTaskRun[]>;
  /** Lifecycle events per originating chat id, served by `/api/threads/{id}/scheduled-task-events`. */
  scheduledTaskEvents?: Record<string, MockScheduledTaskEvent[]>;
  /**
   * `/api/channels/providers` entries (the list is empty and disabled when
   * omitted). `proactive_notifications` defaults to true only for `wecom`.
   */
  channelProviders?: MockChannelProvider[];
  uploadLimits?: {
    max_files: number;
    max_file_size: number;
    max_total_size: number;
  };
  features?: {
    agentsApiEnabled?: boolean;
    browserControlEnabled?: boolean;
    mcpTasksEnabled?: boolean;
    knowledgeScopeSelectionEnabled?: boolean;
    /** Emitted as `scheduled_tasks`; each flag defaults to true. */
    scheduledTasks?: {
      available?: boolean;
      running?: boolean;
      toolEnabled?: boolean;
    };
    /** Emitted as `thread_activity`; unavailable unless enabled, so nothing polls by default. */
    threadActivity?: {
      available?: boolean;
    };
  };
  runStreamHandler?: (route: Route) => Promise<void>;
};

/** One `/api/threads/{id}/scheduled-task-events` row; omitted fields are null. */
export type MockScheduledTaskEvent = {
  id: string;
  task_id: string;
  event: "task_stopped" | "task_paused" | "task_finished";
  reason_code: string;
  task_title?: string | null;
  stop_condition?: string | null;
  run_thread_id?: string | null;
  run_number?: number | null;
  run_status?: MockScheduledTaskRun["status"] | null;
  max_runs?: number | null;
  end_at?: string | null;
  schedule_type?: "once" | "cron" | "interval" | null;
  after_run_id?: string | null;
  created_at: string;
};

export type MockChannelProvider = {
  provider: string;
  display_name: string;
  enabled?: boolean;
  configured?: boolean;
  connection_status?: string;
  proactive_notifications?: boolean;
};

/** One server-originated run change reported by the mocked `/api/thread-activity`. */
export type MockThreadActivityEntry = {
  thread_id: string;
  /** Default `"schedule"`; `null` is the caller's own interactive run (never listed). */
  origin_kind?: "schedule" | "im_channel" | "github" | "extension" | null;
  status?: string;
};

/** Handles a spec can use to drive the mocked backend after `mockLangGraphAPI`. */
export type MockAPIController = {
  /** Add or replace a thread in the thread search results. */
  upsertThread: (thread: MockThread) => void;
  /** Record run changes; the next activity poll after the seed returns them. */
  pushThreadActivity: (...entries: MockThreadActivityEntry[]) => void;
  /** Simulate a read on another device (raises `read_version`). */
  bumpReadVersion: () => void;
  /**
   * Replace the scheduled tasks every task route serves (the list, one task,
   * a chat's tasks), e.g. to flip a task to paused or delete it.
   */
  setScheduledTasks: (tasks: MockScheduledTask[]) => void;
  /** Replace the lifecycle events of an originating chat. */
  setScheduledTaskEvents: (
    threadId: string,
    events: MockScheduledTaskEvent[],
  ) => void;
  /** Thread ids of every `POST /api/threads/{id}/read`, in order. */
  readonly readRequests: readonly string[];
};

function scheduledTaskEventResponse(event: MockScheduledTaskEvent) {
  return {
    task_title: null,
    stop_condition: null,
    run_thread_id: null,
    run_number: null,
    run_status: null,
    max_runs: null,
    end_at: null,
    schedule_type: null,
    after_run_id: null,
    ...event,
  };
}

export type MockScheduledTask = {
  id: string;
  thread_id: string | null;
  context_mode?: "fresh_thread_per_run" | "reuse_thread";
  assistant_id?: string | null;
  last_thread_id?: string | null;
  title: string;
  prompt: string;
  schedule_type: "once" | "cron" | "interval";
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
  goal_objective?: string | null;
  max_runs?: number | null;
  end_at?: string | null;
  origin_thread_id?: string | null;
  standing_notes?: string[] | null;
  stop_condition?: string | null;
  automatic_runs_used?: number;
  active_run_status?: "queued" | "launching" | "running" | null;
  created_at: string;
  updated_at: string;
};

export type MockScheduledTaskRun = {
  id: string;
  task_id: string;
  thread_id: string | null;
  run_id: string | null;
  scheduled_for: string;
  trigger: "scheduled" | "manual";
  status:
    | "queued"
    | "launching"
    | "running"
    | "success"
    | "unmet"
    | "failed"
    | "skipped"
    | "interrupted";
  error: string | null;
  goal_objective?: string | null;
  goal_verdict?: Record<string, unknown> | null;
  stop_requested_run_id?: string | null;
  attempt_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  run_number?: number | null;
  total_tokens?: number | null;
  summary?: string | null;
};

/** Fill the response fields newer backends always send, so older fixtures stay valid. */
function scheduledTaskResponse(task: MockScheduledTask) {
  return {
    context_mode: "fresh_thread_per_run",
    last_thread_id: null,
    assistant_id: null,
    goal_objective: null,
    max_runs: null,
    end_at: null,
    origin_thread_id: null,
    standing_notes: [],
    stop_condition: null,
    automatic_runs_used: 0,
    active_run_status: null,
    ...task,
    thread_id: task.thread_id ?? null,
  };
}

function scheduledTaskNotFound(route: Route) {
  return route.fulfill({
    status: 404,
    contentType: "application/json",
    body: JSON.stringify({
      detail: { code: "task_not_found", message: "Scheduled task not found" },
    }),
  });
}

const CLEARABLE_TASK_FIELDS = [
  "goal_objective",
  "max_runs",
  "end_at",
  "stop_condition",
] as const;

/** PATCH/resume semantics: a present key replaces the value; `null` clears the clearable fields. */
function applyClearableTaskFields(
  task: MockScheduledTask,
  payload: Record<string, unknown>,
): MockScheduledTask {
  const next: MockScheduledTask = { ...task };
  for (const key of CLEARABLE_TASK_FIELDS) {
    if (!(key in payload)) continue;
    const value = payload[key];
    if (value === null || value === "") {
      next[key] = null;
    } else if (key === "max_runs" && typeof value === "number") {
      next.max_runs = value;
    } else if (key !== "max_runs" && typeof value === "string") {
      next[key] = value;
    }
  }
  return next;
}

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

function isHiddenInputMessage(message: unknown) {
  if (typeof message !== "object" || message === null) {
    return false;
  }
  const additionalKwargs = Reflect.get(message, "additional_kwargs");
  return (
    typeof additionalKwargs === "object" &&
    additionalKwargs !== null &&
    Reflect.get(additionalKwargs, "hide_from_ui") === true
  );
}

function visibleInputMessages(messages: unknown[]) {
  return messages.filter((message) => !isHiddenInputMessage(message));
}

function mockMessageRunId(message: unknown, fallback: string) {
  if (typeof message === "object" && message !== null) {
    const runId = Reflect.get(message, "run_id");
    if (typeof runId === "string" && runId.length > 0) {
      return runId;
    }
  }
  return fallback;
}

function visibleRunInputMessages(route: Route) {
  try {
    const body = route.request().postDataJSON() as {
      input?: { messages?: unknown[] };
    };
    return visibleInputMessages(body.input?.messages ?? []);
  } catch {
    return [];
  }
}

function messageId(message: unknown): string | undefined {
  if (typeof message !== "object" || message === null) {
    return undefined;
  }
  const raw = Reflect.get(message, "id");
  return typeof raw === "string" ? raw : undefined;
}

function branchMessagesFromTurn(messages: unknown[], targetIds: Set<string>) {
  let targetEndIndex = -1;
  for (const [index, message] of messages.entries()) {
    const id = messageId(message);
    if (id && targetIds.has(id)) {
      targetEndIndex = Math.max(targetEndIndex, index);
    }
  }
  return targetEndIndex >= 0 ? messages.slice(0, targetEndIndex + 1) : messages;
}

function mockStreamMessages(
  route?: Route,
  inputMessages?: unknown[],
  responseMessage: Record<string, unknown> = {
    type: "ai",
    id: "msg-ai-1",
    content: "Hello from DeerFlow!",
  },
) {
  const submittedMessages = inputMessages
    ? visibleInputMessages(inputMessages)
    : route
      ? visibleRunInputMessages(route)
      : [];
  if (submittedMessages.length > 0) {
    return [...submittedMessages, responseMessage];
  }

  return [
    {
      type: "human",
      id: "msg-human-1",
      content: [{ type: "text", text: "Hello" }],
    },
    responseMessage,
  ];
}

function runStreamThreadId(route: Route) {
  const pathThreadId = /\/threads\/([^/]+)\/runs\/stream/.exec(
    new URL(route.request().url()).pathname,
  )?.[1];
  if (pathThreadId) {
    return pathThreadId;
  }

  try {
    const body = route.request().postDataJSON() as {
      thread_id?: string;
      threadId?: string;
      context?: { thread_id?: string };
      config?: { configurable?: { thread_id?: string } };
    };
    return (
      body.thread_id ??
      body.threadId ??
      body.context?.thread_id ??
      body.config?.configurable?.thread_id ??
      MOCK_THREAD_ID
    );
  } catch {
    return MOCK_THREAD_ID;
  }
}

// ---------------------------------------------------------------------------
// mockLangGraphAPI
// ---------------------------------------------------------------------------

/**
 * Mock all LangGraph API endpoints that the frontend calls on page load and
 * during message sending.  Without these mocks the pages would hang waiting
 * for a real backend.
 */
export function mockLangGraphAPI(
  page: Page,
  options?: MockAPIOptions,
): MockAPIController {
  void page.route("**/api/plugins", (route) => route.fulfill({ json: [] }));
  let threads = [...(options?.threads ?? [])];
  const projectsList = (options?.projects ?? []).map((project) => ({
    instructions: "",
    presentation: {},
    status: "active" as const,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...project,
  }));
  let projectDocuments = [...(options?.projectDocuments ?? [])];
  let trashDocuments = [...(options?.trashDocuments ?? [])];
  const threadFileGroups = [...(options?.threadFileGroups ?? [])];
  let projectDocumentSequence = 0;
  const agents = options?.agents ?? [];
  const skills = options?.skills ?? DEFAULT_SKILLS;
  const scheduledTasks = options?.scheduledTasks ?? [];
  let mutableScheduledTasks: MockScheduledTask[] = [...scheduledTasks];
  const mutableTaskRuns: Record<string, MockScheduledTaskRun[]> =
    Object.fromEntries(
      Object.entries(options?.scheduledTaskRuns ?? {}).map(([id, runs]) => [
        id,
        [...runs],
      ]),
    );
  const uploadLimits = options?.uploadLimits ?? {
    max_files: 10,
    max_file_size: 50 * 1024 * 1024,
    max_total_size: 100 * 1024 * 1024,
  };
  let larkIntegrationStatus = {
    installed: false,
    version: "v1.0.65",
    manifest_version: null as string | null,
    latest_available_version: "v1.0.65" as string | null,
    runtime_version_mismatch: false,
    app_configured: false,
    app_id: null as string | null,
    app_brand: null as string | null,
    skills_expected: 27,
    skills_installed: 0,
    installed_skills: [] as string[],
    enabled_skills: [] as string[],
    install_path: "/tmp/deer-flow/integrations/skills/lark-cli",
    cli: {
      available: false,
      path: null as string | null,
      version: null as string | null,
      error: "lark-cli is not on PATH" as string | null,
    },
    auth: {
      status: "unavailable",
      message: "lark-cli is not installed on the Gateway" as string | null,
      user: null as string | null,
      verified: false,
    },
    sandbox_runtime_mode: "init-container" as
      | "none"
      | "gateway-download"
      | "init-container"
      | "broker",
    sandbox_runtime_probed: true,
    sandbox_runtime_ready: false,
    sandbox_runtime_detail:
      "The provisioner has no lark-cli init image configured (LARK_CLI_INIT_IMAGE)." as
        | string
        | null,
  };
  const featureFlags = {
    agentsApiEnabled: options?.features?.agentsApiEnabled ?? true,
    browserControlEnabled: options?.features?.browserControlEnabled ?? true,
    mcpTasksEnabled: options?.features?.mcpTasksEnabled ?? true,
    knowledgeScopeSelectionEnabled:
      options?.features?.knowledgeScopeSelectionEnabled ?? false,
    scheduledTasks: {
      available: options?.features?.scheduledTasks?.available ?? true,
      running: options?.features?.scheduledTasks?.running ?? true,
      toolEnabled: options?.features?.scheduledTasks?.toolEnabled ?? true,
    },
    threadActivity: {
      available: options?.features?.threadActivity?.available ?? false,
    },
  };
  // Thread activity feed: a run-change log ordered by `seq`, plus the
  // per-user read clock. Cursors are "<seq>:<run id>".
  const activityLog: Array<
    Required<MockThreadActivityEntry> & { seq: number }
  > = [];
  let activitySeq = 100;
  let readVersion = 0;
  const readRequests: string[] = [];
  const scheduledTaskEvents: Record<string, MockScheduledTaskEvent[]> = {
    ...(options?.scheduledTaskEvents ?? {}),
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
    unread: thread.unread ?? false,
  });

  const threadUpdatedAt = (thread: MockThread) =>
    Date.parse(thread.updated_at ?? "2025-01-01T00:00:00Z") || 0;

  const sortThreadSearchResults = (items: readonly MockThread[]) =>
    [...items].sort((left, right) => {
      const pinnedDiff =
        Number(right.metadata?.[THREAD_PINNED_METADATA_KEY] === true) -
        Number(left.metadata?.[THREAD_PINNED_METADATA_KEY] === true);
      return (
        pinnedDiff ||
        threadUpdatedAt(right) - threadUpdatedAt(left) ||
        right.thread_id.localeCompare(left.thread_id)
      );
    });

  const patchThreadMetadata = (
    threadId: string,
    metadata: Record<string, unknown>,
  ) => {
    let updated: MockThread | undefined;
    threads = threads.map((thread) => {
      if (thread.thread_id !== threadId) {
        return thread;
      }
      // Preserve ``updated_at`` for pin/unpin metadata changes; the search mock
      // below mirrors the Gateway's server-side pinned-first ordering.
      updated = {
        ...thread,
        metadata: {
          ...(thread.metadata ?? {}),
          ...metadata,
        },
      };
      return updated;
    });
    return updated;
  };

  const patchThreadTitle = (threadId: string, title: string) => {
    let updated: MockThread | undefined;
    threads = threads.map((thread) => {
      if (thread.thread_id !== threadId) {
        return thread;
      }
      updated = { ...thread, title };
      return updated;
    });
    return updated;
  };

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
      const providers = (options?.channelProviders ?? []).map((provider) => ({
        enabled: true,
        configured: true,
        connectable: true,
        unavailable_reason: null,
        auth_mode: "token",
        connection_status: "not_connected",
        credential_fields: [],
        credential_values: {},
        proactive_notifications: provider.provider === "wecom",
        ...provider,
      }));
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: providers.length > 0,
          providers,
        }),
      });
    }
    return route.fallback();
  });

  // Thread activity feed (`GET /api/thread-activity`): 503 when unavailable,
  // like a memory-backed Gateway; no cursor seeds; a cursor returns the
  // logged changes after it (deduped by thread, latest last).
  void page.route(/\/api\/thread-activity(?:\?|$)/, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    if (!featureFlags.threadActivity.available) {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Thread activity is not available" }),
      });
    }
    const cursor = new URL(route.request().url()).searchParams.get("cursor");
    if (cursor === null) {
      const head = activityLog.at(-1);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          cursor: head ? `${head.seq}:run-${head.seq}` : "0:",
          threads: [],
          truncated: false,
          read_version: readVersion,
        }),
      });
    }
    const match = /^(\d+):/.exec(cursor);
    if (!match) {
      return route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({
          detail: {
            code: "invalid_cursor",
            message: "Invalid activity cursor",
          },
        }),
      });
    }
    const after = Number(match[1]);
    const changed = activityLog.filter((entry) => entry.seq > after);
    const last = changed.at(-1);
    const latest = new Map<string, (typeof changed)[number]>();
    for (const entry of changed) {
      latest.delete(entry.thread_id);
      latest.set(entry.thread_id, entry);
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        cursor: last ? `${last.seq}:run-${last.seq}` : cursor,
        threads: [...latest.values()]
          .filter((entry) => entry.origin_kind !== null)
          .map(({ thread_id, origin_kind, status }) => ({
            thread_id,
            origin_kind,
            status,
          })),
        truncated: false,
        read_version: readVersion,
      }),
    });
  });

  // Mark read (`POST /api/threads/{id}/read`): raises `read_version` only
  // when the thread was unread, like the Gateway.
  void page.route(/\/api\/threads\/[^/]+\/read$/, (route) => {
    if (route.request().method() !== "POST") {
      return route.fallback();
    }
    const parts = new URL(route.request().url()).pathname.split("/");
    const threadId = decodeURIComponent(parts.at(-2) ?? "");
    readRequests.push(threadId);
    const thread = threads.find((item) => item.thread_id === threadId);
    if (!thread) {
      return route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: `Thread ${threadId} not found` }),
      });
    }
    if (thread.unread) {
      threads = threads.map((item) =>
        item.thread_id === threadId ? { ...item, unread: false } : item,
      );
      readVersion += 1;
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ unread: false, read_version: readVersion }),
    });
  });

  // Lifecycle events of an originating chat. Rows outlive their task, so
  // this route never looks at the task list.
  void page.route(
    /\/api\/threads\/[^/]+\/scheduled-task-events(?:\?|$)/,
    (route) => {
      if (route.request().method() !== "GET") {
        return route.fallback();
      }
      const parts = new URL(route.request().url()).pathname.split("/");
      const threadId = decodeURIComponent(parts.at(-2) ?? "");
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          events: (scheduledTaskEvents[threadId] ?? []).map(
            scheduledTaskEventResponse,
          ),
        }),
      });
    },
  );

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
        body: JSON.stringify(mutableScheduledTasks.map(scheduledTaskResponse)),
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
      const created: MockScheduledTask = {
        id: "task-created",
        thread_id: threadId || null,
        context_mode:
          (payload.context_mode as "fresh_thread_per_run" | "reuse_thread") ??
          "fresh_thread_per_run",
        assistant_id:
          typeof payload.assistant_id === "string"
            ? payload.assistant_id
            : "lead_agent",
        last_thread_id: null,
        title,
        prompt,
        schedule_type: payload.schedule_type as "once" | "cron" | "interval",
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
      const stored = applyClearableTaskFields(created, payload);
      mutableScheduledTasks = [stored, ...mutableScheduledTasks];
      mutableTaskRuns[stored.id] = [];
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(scheduledTaskResponse(stored)),
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
        task.id === taskId
          ? { ...task, status: "paused" as const, active_run_status: null }
          : task,
      );
      const task = mutableScheduledTasks.find((item) => item.id === taskId);
      if (!task) return scheduledTaskNotFound(route);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(scheduledTaskResponse(task)),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/scheduled-tasks/*/resume", (route) => {
    if (route.request().method() === "POST") {
      const taskId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
      );
      // Optional renewal body: `max_runs` / `end_at`, `null` clears that cap.
      const renewal = (() => {
        try {
          return (route.request().postDataJSON() ?? {}) as Record<
            string,
            unknown
          >;
        } catch {
          return {};
        }
      })();
      mutableScheduledTasks = mutableScheduledTasks.map((task) =>
        task.id === taskId
          ? {
              ...applyClearableTaskFields(task, {
                ...("max_runs" in renewal
                  ? { max_runs: renewal.max_runs }
                  : {}),
                ...("end_at" in renewal ? { end_at: renewal.end_at } : {}),
              }),
              status: "enabled" as const,
            }
          : task,
      );
      const task = mutableScheduledTasks.find((item) => item.id === taskId);
      if (!task) return scheduledTaskNotFound(route);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(scheduledTaskResponse(task)),
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
      if (!task) return scheduledTaskNotFound(route);
      const threadId = task.thread_id ?? `trial-thread-${taskId}`;
      const runId = `run-${taskId}`;
      mutableTaskRuns[taskId] = [
        {
          id: `task-run-${taskId}`,
          task_id: taskId,
          thread_id: threadId,
          run_id: runId,
          scheduled_for: "2026-07-01T00:00:00+00:00",
          trigger: "manual",
          status: "success",
          error: null,
          attempt_count: 1,
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
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: taskId,
          triggered: true,
          outcome: "launched",
          existing: false,
          thread_id: threadId,
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/scheduled-tasks/*", (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      const taskId = decodeURIComponent(
        new URL(request.url()).pathname.split("/").at(-1) ?? "",
      );
      const task = mutableScheduledTasks.find((item) => item.id === taskId);
      if (!task) return scheduledTaskNotFound(route);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(scheduledTaskResponse(task)),
      });
    }
    if (request.method() === "PATCH") {
      const taskId = decodeURIComponent(
        new URL(request.url()).pathname.split("/").at(-1) ?? "",
      );
      const payload = request.postDataJSON() as Record<string, unknown>;
      let updated: MockScheduledTask | undefined;
      mutableScheduledTasks = mutableScheduledTasks.map((task) => {
        if (task.id !== taskId) {
          return task;
        }
        updated = {
          ...applyClearableTaskFields(task, payload),
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
      if (!updated) return scheduledTaskNotFound(route);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(scheduledTaskResponse(updated)),
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
          mutableScheduledTasks.flatMap((task) => {
            const runInThread = (mutableTaskRuns[task.id] ?? []).find(
              (run) => run.thread_id === threadId,
            );
            const relation =
              task.origin_thread_id === threadId
                ? "origin"
                : task.thread_id === threadId
                  ? "reuse"
                  : runInThread
                    ? "run"
                    : null;
            if (!relation) return [];
            return [
              {
                ...scheduledTaskResponse(task),
                thread_relation: relation,
                thread_run:
                  relation === "run" && runInThread
                    ? {
                        run_number: runInThread.run_number ?? null,
                        trigger: runInThread.trigger,
                        scheduled_for: runInThread.scheduled_for,
                        status: runInThread.status,
                      }
                    : null,
              },
            ];
          }),
        ),
      });
    }
    return route.fallback();
  });

  void page.route(/\/api\/scheduled-tasks\/[^/]+\/runs(?:\?|$)/, (route) => {
    if (route.request().method() === "GET") {
      const url = new URL(route.request().url());
      const taskId = decodeURIComponent(url.pathname.split("/").at(-2) ?? "");
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 50);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          (mutableTaskRuns[taskId] ?? []).slice(offset, offset + limit),
        ),
      });
    }
    return route.fallback();
  });

  // Thread search — sidebar thread list & chats list page
  void page.route(/\/api\/(?:langgraph\/)?threads\/search$/, async (route) => {
    let body = sortThreadSearchResults(threads).map(threadSearchResult);

    let limit: number | undefined;
    let offset = 0;
    try {
      const postData = route.request().postDataJSON() as {
        archived?: boolean;
        limit?: number;
        offset?: number;
        metadata?: Record<string, unknown>;
      } | null;
      if (postData) {
        if (typeof postData.archived === "boolean") {
          body = body.filter(
            (thread) =>
              (Reflect.get(thread.metadata, "deerflow_archived") === true) ===
              postData.archived,
          );
        }
        if (typeof postData.limit === "number") {
          limit = postData.limit;
        }
        if (typeof postData.offset === "number") {
          offset = postData.offset;
        }
        if (postData.metadata && typeof postData.metadata === "object") {
          body = body.filter((thread) =>
            Object.entries(postData.metadata ?? {}).every(
              ([key, value]) => thread.metadata?.[key] === value,
            ),
          );
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
      const threadId =
        (options?.honorRequestedThreadId
          ? (route.request().postDataJSON() as { thread_id?: string } | null)
              ?.thread_id
          : undefined) ?? MOCK_THREAD_ID;
      upsertThread({
        thread_id: threadId,
        title: "New Chat",
        updated_at: new Date().toISOString(),
        messages: options?.createdThreadMessages ?? mockStreamMessages(),
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          thread_id: threadId,
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
      const body = route.request().postDataJSON() as {
        metadata?: Record<string, unknown>;
      };
      const updated = body.metadata
        ? patchThreadMetadata(threadId, body.metadata)
        : matchingThread;
      if (!updated) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Thread not found" }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(threadSearchResult(updated)),
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

  void page.route("**/api/threads", (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as {
        thread_id?: string;
        metadata?: Record<string, unknown>;
        project_id?: string;
      };
      const threadId = body.thread_id ?? MOCK_SIDECAR_THREAD_ID;
      // The backend stamps `metadata.deerflow_project_id` from the assigned
      // project_id column; mirror that so project membership is readable.
      const metadata = {
        ...body.metadata,
        ...(body.project_id
          ? { [THREAD_PROJECT_METADATA_KEY]: body.project_id }
          : {}),
      };
      // Mirror the backend idempotency contract: a repeat POST for an
      // existing thread_id returns the record unchanged (goal and other
      // state intact) instead of resetting it.
      const existing = threads.find((thread) => thread.thread_id === threadId);
      if (existing) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            thread_id: threadId,
            created_at: existing.updated_at ?? new Date().toISOString(),
            updated_at: existing.updated_at ?? new Date().toISOString(),
            metadata: existing.metadata ?? {},
            status: "idle",
            values: {},
          }),
        });
      }
      upsertThread({
        thread_id: threadId,
        title: "Side chat",
        updated_at: new Date().toISOString(),
        metadata: metadata,
        messages: [],
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          thread_id: threadId,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          metadata: metadata,
          status: "idle",
          values: {},
        }),
      });
    }
    return route.fallback();
  });

  void page.route(/\/api\/threads\/[^/]+$/, (route) => {
    if (route.request().method() === "PATCH") {
      const threadId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-1) ?? "",
      );
      const body = route.request().postDataJSON() as {
        metadata?: Record<string, unknown>;
      };
      const matchingThread = threads.find(
        (thread) => thread.thread_id === threadId,
      );
      const updated = body.metadata
        ? patchThreadMetadata(threadId, body.metadata)
        : matchingThread;
      if (!updated) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: `Thread ${threadId} not found` }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(threadSearchResult(updated)),
      });
    }
    if (route.request().method() === "DELETE") {
      const threadId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-1) ?? "",
      );
      // Mirror the gateway's `require_existing=True` ownership guard: deleting
      // an already-removed thread 404s. `useDeleteThread` first deletes via the
      // LangGraph route (which drops the thread_meta row) and then hits this
      // route, so this reproduces the real double-delete 404 the frontend must
      // treat as idempotent success.
      if (!threads.some((thread) => thread.thread_id === threadId)) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: `Thread ${threadId} not found` }),
        });
      }
      threads = threads.filter((thread) => thread.thread_id !== threadId);
      return route.fulfill({
        status: 204,
      });
    }
    return route.fallback();
  });

  // Projects API — Phase 1 default-empty mocks so existing specs are
  // unaffected; project-aware specs register their own routes on top.
  void page.route(/\/api\/projects(\?|$)/, (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ projects: projectsList }),
      });
    }
    return route.fallback();
  });

  // Phase 2 project/trash API — default-empty mocks so project-unaware specs
  // are unaffected; project specs seed rows via MockAPIOptions and drive the
  // stateful routes below (upload -> shelf -> attach -> trash -> restore ->
  // purge mirrors the gateway's lifecycle, spec §6.5/§8).

  const json = (status: number, body: unknown) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const notFound = (detail: string) => json(404, { detail });
  const projectDocumentResponse = (document: MockProjectDocument) => ({
    id: document.id,
    name: document.name,
    size_bytes: document.size_bytes,
    sha256: document.sha256 ?? "mock-sha256",
    content_missing: document.content_missing ?? false,
    source_thread_id: document.source_thread_id ?? null,
    source_kind: document.source_kind ?? null,
    source_name: document.source_name ?? null,
    created_at: document.created_at ?? "2026-01-01T00:00:00Z",
    updated_at: document.updated_at ?? "2026-01-01T00:00:00Z",
  });
  const findProject = (projectId: string) =>
    projectsList.find((project) => project.id === projectId);

  void page.route(/\/api\/projects\/([^/]+)$/, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    const projectId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-1) ?? "",
    );
    const project = findProject(projectId);
    if (!project) {
      return route.fulfill(notFound("Project not found"));
    }
    return route.fulfill(json(200, project));
  });

  // Registered after the catch-all ``/api/projects/{id}`` route so the last-
  // registered-wins order lets ``config`` resolve here instead of 404ing as
  // a project id — the gateway declares the route before ``/{project_id}``
  // for the same reason.
  void page.route(/\/api\/projects\/config$/, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    return route.fulfill(
      json(200, {
        instructions_max_bytes:
          options?.projectsConfig?.instructions_max_bytes ?? 8192,
        trash_retention_days:
          options?.projectsConfig?.trash_retention_days ?? 30,
      }),
    );
  });

  void page.route(/\/api\/projects\/([^/]+)\/threads$/, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    const projectId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
    );
    if (!findProject(projectId)) {
      return route.fulfill(notFound("Project not found"));
    }
    const members = threads
      .filter(
        (thread) =>
          thread.metadata?.[THREAD_PROJECT_METADATA_KEY] === projectId,
      )
      .map((thread) => ({
        thread_id: thread.thread_id,
        display_name: thread.title ?? null,
        metadata: thread.metadata ?? {},
        created_at: thread.updated_at,
        updated_at: thread.updated_at,
      }));
    return route.fulfill(json(200, members));
  });

  void page.route(/\/api\/projects\/([^/]+)\/documents(?:\?|$)/, (route) => {
    const projectId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
    );
    if (!findProject(projectId)) {
      return route.fulfill(notFound("Project not found"));
    }
    if (route.request().method() === "GET") {
      const search = new URL(route.request().url()).searchParams;
      const limit = Number(search.get("limit") ?? 100);
      const offset = Number(search.get("offset") ?? 0);
      const all = projectDocuments
        .filter((document) => document.project_id === projectId)
        .map(projectDocumentResponse);
      return route.fulfill(
        json(200, {
          documents: all.slice(offset, offset + limit),
          total: all.length,
          limit,
          offset,
        }),
      );
    }
    if (route.request().method() === "POST") {
      const body = route.request().postData() ?? "";
      const filename = /filename="([^"]+)"/.exec(body)?.[1] ?? "upload.bin";
      projectDocumentSequence += 1;
      const document: MockProjectDocument = {
        id: `mock-doc-${projectDocumentSequence}`,
        project_id: projectId,
        name: filename,
        size_bytes: body.length,
        source_thread_id: null,
        source_kind: null,
        source_name: null,
      };
      projectDocuments = [...projectDocuments, document];
      return route.fulfill(
        json(201, {
          document: projectDocumentResponse(document),
          deduplicated: false,
        }),
      );
    }
    return route.fallback();
  });

  void page.route(
    /\/api\/projects\/([^/]+)\/documents\/([^/]+)\/content$/,
    (route) => {
      if (route.request().method() !== "GET") {
        return route.fallback();
      }
      const parts = new URL(route.request().url()).pathname.split("/");
      const projectId = decodeURIComponent(parts.at(-4) ?? "");
      const documentId = decodeURIComponent(parts.at(-2) ?? "");
      const document = projectDocuments.find(
        (candidate) =>
          candidate.id === documentId && candidate.project_id === projectId,
      );
      if (!document) {
        return route.fulfill(notFound("Project document not found"));
      }
      return route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: `mock content of ${document.name}`,
      });
    },
  );

  void page.route(/\/api\/projects\/([^/]+)\/documents\/([^/]+)$/, (route) => {
    if (route.request().method() !== "DELETE") {
      return route.fallback();
    }
    const parts = new URL(route.request().url()).pathname.split("/");
    const projectId = decodeURIComponent(parts.at(-3) ?? "");
    const documentId = decodeURIComponent(parts.at(-1) ?? "");
    const document = projectDocuments.find(
      (candidate) =>
        candidate.id === documentId && candidate.project_id === projectId,
    );
    if (!document) {
      return route.fulfill(notFound("Project document not found"));
    }
    const project = findProject(projectId);
    projectDocuments = projectDocuments.filter(
      (candidate) => candidate.id !== documentId,
    );
    trashDocuments = [
      {
        ...document,
        trashed_at: new Date().toISOString(),
        trash_origin: {
          project_id: projectId,
          project_name: project?.name ?? "Unknown",
        },
      },
      ...trashDocuments,
    ];
    return route.fulfill({ status: 204 });
  });

  void page.route(
    /\/api\/projects\/([^/]+)\/documents\/from-thread$/,
    (route) => {
      if (route.request().method() !== "POST") {
        return route.fallback();
      }
      const projectId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-3) ?? "",
      );
      if (!findProject(projectId)) {
        return route.fulfill(notFound("Project not found"));
      }
      const body = route.request().postDataJSON() as {
        thread_id: string;
        kind: "upload" | "output";
        name: string;
        shelf_name?: string;
      };
      projectDocumentSequence += 1;
      const document: MockProjectDocument = {
        id: `mock-doc-${projectDocumentSequence}`,
        project_id: projectId,
        name: body.shelf_name ?? body.name,
        size_bytes: 128,
        source_thread_id: body.thread_id,
        source_kind: body.kind,
        source_name: body.name,
      };
      projectDocuments = [...projectDocuments, document];
      return route.fulfill(
        json(201, {
          document: projectDocumentResponse(document),
          deduplicated: false,
        }),
      );
    },
  );

  void page.route(
    /\/api\/projects\/([^/]+)\/documents\/([^/]+)\/attach-to-thread\/([^/]+)$/,
    (route) => {
      if (route.request().method() !== "POST") {
        return route.fallback();
      }
      const parts = new URL(route.request().url()).pathname.split("/");
      const projectId = decodeURIComponent(parts.at(-5) ?? "");
      const documentId = decodeURIComponent(parts.at(-3) ?? "");
      const threadId = decodeURIComponent(parts.at(-1) ?? "");
      const document = projectDocuments.find(
        (candidate) =>
          candidate.id === documentId && candidate.project_id === projectId,
      );
      if (!document || !threads.some((t) => t.thread_id === threadId)) {
        return route.fulfill(notFound("Project document not found"));
      }
      return route.fulfill(
        json(200, {
          filename: document.name,
          size_bytes: document.size_bytes,
          virtual_path: `/mnt/user-data/uploads/${document.name}`,
          artifact_url: `/api/threads/${threadId}/artifacts/mnt/user-data/uploads/${encodeURIComponent(document.name)}`,
        }),
      );
    },
  );

  void page.route(/\/api\/projects\/([^/]+)\/thread-files(?:\?|$)/, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    const projectId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
    );
    if (!findProject(projectId)) {
      return route.fulfill(notFound("Project not found"));
    }
    const projectThreadIds = new Set(
      threads
        .filter(
          (thread) =>
            thread.metadata?.[THREAD_PROJECT_METADATA_KEY] === projectId,
        )
        .map((thread) => thread.thread_id),
    );
    const groups = threadFileGroups
      .filter((group) => projectThreadIds.has(group.thread_id))
      .map((group) => ({ truncated: false, ...group }));
    return route.fulfill(
      json(200, {
        groups,
        next_offset: null,
        truncated: groups.some((group) => group.truncated),
      }),
    );
  });

  void page.route(/\/api\/trash\/documents(?:\?|$)/, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    const search = new URL(route.request().url()).searchParams;
    const limit = Number(search.get("limit") ?? 100);
    const offset = Number(search.get("offset") ?? 0);
    const all = trashDocuments.map((document) => ({
      ...projectDocumentResponse(document),
      trashed_at: document.trashed_at,
      trash_origin: document.trash_origin ?? null,
    }));
    return route.fulfill(
      json(200, {
        documents: all.slice(offset, offset + limit),
        total: all.length,
        limit,
        offset,
      }),
    );
  });

  void page.route(/\/api\/trash\/documents\/([^/]+)\/restore$/, (route) => {
    if (route.request().method() !== "POST") {
      return route.fallback();
    }
    const documentId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
    );
    const document = trashDocuments.find(
      (candidate) => candidate.id === documentId,
    );
    if (!document) {
      return route.fulfill(notFound("Trash document not found"));
    }
    let target: string | undefined;
    try {
      const body = route.request().postDataJSON() as {
        project_id?: string | null;
      };
      target = body.project_id ?? undefined;
    } catch {
      target = undefined;
    }
    if (!target) {
      const originId = document.trash_origin?.project_id;
      const origin = originId ? findProject(originId) : undefined;
      if (origin && (origin.status ?? "active") === "active") {
        target = origin.id;
      }
    }
    const targetProject = target ? findProject(target) : undefined;
    if (!targetProject || (targetProject.status ?? "active") !== "active") {
      return route.fulfill(notFound("Trash document not found"));
    }
    trashDocuments = trashDocuments.filter(
      (candidate) => candidate.id !== documentId,
    );
    const restored: MockProjectDocument = {
      ...document,
      project_id: targetProject.id,
    };
    projectDocuments = [...projectDocuments, restored];
    return route.fulfill(
      json(200, {
        outcome: "restored",
        document: projectDocumentResponse(restored),
      }),
    );
  });

  void page.route(/\/api\/trash\/documents\/([^/]+)\/purge$/, (route) => {
    if (route.request().method() !== "POST") {
      return route.fallback();
    }
    const documentId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
    );
    if (!trashDocuments.some((candidate) => candidate.id === documentId)) {
      return route.fulfill(notFound("Trash document not found"));
    }
    trashDocuments = trashDocuments.filter(
      (candidate) => candidate.id !== documentId,
    );
    return route.fulfill({ status: 204 });
  });

  void page.route(/\/api\/trash\/purge$/, (route) => {
    if (route.request().method() !== "POST") {
      return route.fallback();
    }
    const purged = trashDocuments.length;
    trashDocuments = [];
    return route.fulfill(json(200, { purged }));
  });

  void page.route(/\/api\/threads\/[^/]+\/move$/, (route) => {
    if (route.request().method() === "POST") {
      const threadId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-2) ?? "",
      );
      const body = route.request().postDataJSON() as {
        project_id?: string | null;
      };
      const updated = patchThreadMetadata(threadId, {
        [THREAD_PROJECT_METADATA_KEY]: body.project_id ?? null,
      });
      if (!updated) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: `Thread ${threadId} not found` }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(threadSearchResult(updated)),
      });
    }
    return route.fallback();
  });

  void page.route(/\/api\/threads\/[^/]+\/branches$/, (route) => {
    if (route.request().method() === "POST") {
      const pathParts = new URL(route.request().url()).pathname.split("/");
      const sourceThreadId = decodeURIComponent(pathParts.at(-2) ?? "");
      const sourceThread = threads.find(
        (thread) => thread.thread_id === sourceThreadId,
      );
      const body = route.request().postDataJSON() as {
        message_id?: string;
        message_ids?: string[];
        title?: string;
      };
      const targetIds = new Set(
        [body.message_id, ...(body.message_ids ?? [])].filter(
          (id): id is string => typeof id === "string" && id.length > 0,
        ),
      );
      let sourceTitle = sourceThread?.title?.trim();
      if (sourceThread?.metadata?.deerflow_branch === true) {
        sourceTitle = sourceTitle?.replace(/^(Branch:\s*)+/i, "").trim();
      }
      const sourceSequence =
        sourceThread?.metadata?.deerflow_branch === true &&
        Number.isSafeInteger(sourceThread.metadata.branch_title_sequence) &&
        Number(sourceThread.metadata.branch_title_sequence) >= 2 &&
        Number(sourceThread.metadata.branch_title_sequence) <
          Number.MAX_SAFE_INTEGER
          ? Number(sourceThread.metadata.branch_title_sequence)
          : undefined;
      const sequence = sourceSequence === undefined ? 2 : sourceSequence + 1;
      const sourceSuffix = sourceSequence ? ` (${sourceSequence})` : undefined;
      const baseTitle =
        sourceSuffix && sourceTitle?.endsWith(sourceSuffix)
          ? sourceTitle.slice(0, -sourceSuffix.length).trimEnd()
          : sourceTitle;
      const title =
        body.title ??
        (baseTitle
          ? `${baseTitle.slice(0, 256 - ` (${sequence})`.length).trimEnd()} (${sequence})`
          : undefined);

      upsertThread({
        thread_id: MOCK_THREAD_ID_2,
        title,
        updated_at: new Date().toISOString(),
        metadata: {
          deerflow_branch: true,
          ...(!body.title && title ? { branch_title_sequence: sequence } : {}),
          branch_parent_thread_id: sourceThreadId,
          branch_parent_message_id: body.message_id,
          branch_parent_checkpoint_id: "mock-checkpoint",
        },
        messages: branchMessagesFromTurn(
          sourceThread?.messages ?? [],
          targetIds,
        ),
      });

      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          thread_id: MOCK_THREAD_ID_2,
          parent_thread_id: sourceThreadId,
          parent_checkpoint_id: "mock-checkpoint",
          branched_from_message_id: body.message_id,
          workspace_clone_mode: "current_thread_best_effort",
        }),
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

  // Token usage — the chat header polls this per thread. Without a mock the
  // request falls through to a gateway that is not running under Playwright,
  // and a 401 there redirects the whole page to /login mid-test.
  void page.route("**/api/threads/*/token-usage", (route) => {
    if (route.request().method() === "GET") {
      const threadId = /\/api\/threads\/([^/]+)\/token-usage/.exec(
        route.request().url(),
      )?.[1];
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          thread_id: threadId ?? "unknown",
          total_tokens: 0,
          total_input_tokens: 0,
          total_output_tokens: 0,
          total_runs: 0,
          by_model: {},
          by_caller: { lead_agent: 0, subagent: 0, middleware: 0 },
          context_usage: null,
        }),
      });
    }
    return route.fallback();
  });

  // MCP background tasks — same fallthrough-to-401 problem as token-usage.
  void page.route("**/api/threads/*/mcp-tasks*", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    }
    return route.fallback();
  });

  // Workspace changes — the run-scoped badge query. Unmocked it 401s against
  // the absent gateway and the fetcher redirects the page to /login.
  void page.route("**/api/threads/*/runs/*/workspace-changes*", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          run_id: "mock-run",
          thread_id: "mock-thread",
          status: "success",
          summary: {
            created: 0,
            modified: 0,
            deleted: 0,
            symlink_created: 0,
            additions: 0,
            deletions: 0,
            truncated: false,
          },
          changes: [],
        }),
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
    const url = new URL(route.request().url());
    const threadId = decodeURIComponent(url.pathname.split("/").at(-2) ?? "");
    const matchingThread = threads.find(
      (thread) => thread.thread_id === threadId,
    );

    if (route.request().method() === "GET") {
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
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as {
        values?: { title?: unknown };
      };
      const updated =
        typeof body.values?.title === "string"
          ? patchThreadTitle(threadId, body.values.title)
          : matchingThread;
      if (!updated) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Thread not found" }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          configurable: {
            thread_id: threadId,
            checkpoint_ns: "",
            checkpoint_id: "mock-checkpoint",
          },
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

  void page.route(/\/api\/threads\/([^/]+)\/messages\/page/, (route) => {
    if (route.request().method() === "GET") {
      const url = route.request().url();
      const matchingThread = threads.find((t) =>
        url.includes(`/api/threads/${t.thread_id}/messages/page`),
      );
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: (matchingThread?.messages ?? []).map((message, index) => ({
            run_id: mockMessageRunId(
              message,
              `run-${matchingThread?.thread_id ?? "unknown"}`,
            ),
            seq: index + 1,
            content: message,
            metadata: { caller: "lead_agent" },
            created_at: `2025-01-01T00:00:${String(index).padStart(2, "0")}Z`,
          })),
          has_more: false,
          next_before_seq: null,
        }),
      });
    }
    return route.fallback();
  });

  // Run stream — returns a minimal SSE response with an AI message
  const handleMockRunStream =
    options?.runStreamHandler ??
    ((route: Route) => {
      const threadId = runStreamThreadId(route);
      const existingThread = threads.find(
        (thread) => thread.thread_id === threadId,
      );
      const fallbackGoal = threads.find((thread) => thread.goal)?.goal ?? null;
      const goal = existingThread?.goal ?? fallbackGoal;
      upsertThread({
        thread_id: threadId,
        title: threadId === MOCK_SIDECAR_THREAD_ID ? "Side chat" : "New Chat",
        updated_at: new Date().toISOString(),
        goal,
        metadata: existingThread?.metadata,
        messages: mockStreamMessages(route),
      });
      return handleRunStream(route, { goal });
    });

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

  // Feature flags — frontend gates UI (e.g. agents/browser) on these. Default to
  // enabled so existing tests exercise the normal path; tests that need the
  // disabled state override this route after calling mockLangGraphAPI.
  void page.route("**/api/features", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          agents_api: { enabled: featureFlags.agentsApiEnabled },
          browser_control: { enabled: featureFlags.browserControlEnabled },
          mcp_tasks: { enabled: featureFlags.mcpTasksEnabled },
          knowledge_base: {
            scope_selection_enabled:
              featureFlags.knowledgeScopeSelectionEnabled,
          },
          scheduled_tasks: {
            available: featureFlags.scheduledTasks.available,
            running: featureFlags.scheduledTasks.running,
            tool_enabled: featureFlags.scheduledTasks.toolEnabled,
            min_interval_seconds: 60,
          },
          thread_activity: {
            available: featureFlags.threadActivity.available,
          },
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/mcp/config", (route) =>
    route.fulfill({ json: { mcp_servers: {} } }),
  );

  void page.route("**/api/mcp/personal/config", (route) =>
    route.fulfill({ json: { mcp_servers: {} } }),
  );

  // Skills list — capability center and slash autocomplete
  void page.route("**/api/capabilities/catalog", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: readFileSync(
        path.resolve(
          process.cwd(),
          "../backend/packages/harness/deerflow/capabilities/builtin.json",
        ),
        "utf8",
      ),
    }),
  );
  void page.route("**/api/capabilities/installations/*", (route) => {
    const adapter = new URL(route.request().url()).pathname.split("/").pop();
    const items =
      adapter === "lark"
        ? [
            {
              id: "lark",
              plugin_id: "lark",
              adapter: "lark",
              name: "Lark / Feishu",
              reference: "lark",
              installed: larkIntegrationStatus.installed,
              enabled: null,
              version: null,
              auth_status: "required",
              health: "unknown",
              scope: "user",
              category: null,
              icon: null,
            },
          ]
        : adapter === "skills"
          ? skills.map((skill) => ({
              id: `skill:${skill.category ?? "public"}:${skill.name}`,
              plugin_id: null,
              adapter: "skills",
              name: skill.name,
              reference: skill.name,
              description: skill.description,
              installed: true,
              enabled: skill.enabled ?? true,
              version: null,
              auth_status: "not_required",
              health: "unknown",
              scope: "deployment",
              category: skill.category,
              icon: null,
            }))
          : [];
    return route.fulfill({ json: { items, can_manage: true } });
  });

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

  void page.route("**/api/integrations/lark/status", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(larkIntegrationStatus),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/integrations/lark/install", (route) => {
    if (route.request().method() === "POST") {
      larkIntegrationStatus = {
        installed: true,
        version: "v1.0.65",
        manifest_version: "v1.0.65",
        latest_available_version: "v1.0.65",
        runtime_version_mismatch: false,
        app_configured: false,
        app_id: null,
        app_brand: null,
        skills_expected: 27,
        skills_installed: 3,
        installed_skills: ["lark-doc", "lark-im", "lark-shared"],
        enabled_skills: ["lark-doc", "lark-im", "lark-shared"],
        install_path: "/tmp/deer-flow/integrations/skills/lark-cli",
        cli: {
          available: true,
          path: "/usr/bin/lark-cli",
          version: "lark-cli version v1.0.65",
          error: null,
        },
        auth: {
          status: "not_configured",
          message: "lark-cli auth is not configured",
          user: null,
          verified: false,
        },
        sandbox_runtime_mode: "init-container",
        sandbox_runtime_probed: true,
        sandbox_runtime_ready: true,
        sandbox_runtime_detail: null,
      };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          installed_skills: ["lark-doc", "lark-im", "lark-shared"],
          message: "Installed 3 Lark/Feishu skills.",
          status: larkIntegrationStatus,
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/integrations/lark/config/start", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          verification_url: "https://open.feishu.cn/page/cli?user_code=config",
          device_code: "mock-config-device-code",
          generation: "config-generation",
          expires_in: 600,
          interval: 5,
          user_code: "config",
          brand: "feishu",
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/integrations/lark/config/complete", (route) => {
    if (route.request().method() === "POST") {
      larkIntegrationStatus = {
        ...larkIntegrationStatus,
        app_configured: true,
        app_id: "cli_mock",
        app_brand: "feishu",
        auth: {
          status: "not_authorized",
          message: "Lark user authorization is not configured",
          user: null,
          verified: false,
        },
      };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Lark/Feishu connection setup completed.",
          generation: "config-generation",
          status: larkIntegrationStatus,
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/integrations/lark/config/credentials", (route) => {
    if (route.request().method() === "POST") {
      larkIntegrationStatus = {
        ...larkIntegrationStatus,
        app_configured: true,
        app_id: "cli_switched_mock",
        app_brand: "feishu",
        auth: {
          status: "not_authorized",
          message: "Lark user authorization is not configured",
          user: null,
          verified: false,
        },
      };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message:
            "Lark/Feishu app switched. Reconnect to authorize the new app.",
          generation: "switch-generation",
          status: larkIntegrationStatus,
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/integrations/lark/auth/start", (route) => {
    if (route.request().method() === "POST") {
      const request = route.request().postDataJSON() as {
        generation?: string;
      };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          verification_url: "https://open.feishu.cn/auth/mock-device",
          device_code: "mock-device-code",
          generation: request.generation ?? "auth-generation",
          expires_in: 600,
          user_code: null,
          hint: null,
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/integrations/lark/auth/complete", (route) => {
    if (route.request().method() === "POST") {
      larkIntegrationStatus = {
        ...larkIntegrationStatus,
        auth: {
          status: "authenticated",
          message: "Lark/Feishu authorization is live-verified.",
          user: "Alice",
          verified: true,
        },
      };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Lark/Feishu authorization completed.",
          status: larkIntegrationStatus,
        }),
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

  return {
    upsertThread,
    pushThreadActivity: (...entries) => {
      for (const entry of entries) {
        activitySeq += 1;
        activityLog.push({
          seq: activitySeq,
          thread_id: entry.thread_id,
          // Server-originated unless a spec passes `null` (an interactive run).
          origin_kind:
            entry.origin_kind === undefined ? "schedule" : entry.origin_kind,
          status: entry.status ?? "success",
        });
      }
    },
    bumpReadVersion: () => {
      readVersion += 1;
    },
    setScheduledTasks: (tasks) => {
      mutableScheduledTasks = [...tasks];
    },
    setScheduledTaskEvents: (threadId, events) => {
      scheduledTaskEvents[threadId] = events;
    },
    get readRequests() {
      return readRequests;
    },
  };
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
  inputMessages?: unknown[],
  options?: {
    responseMessage?: Record<string, unknown>;
    messageMetadata?: Record<string, unknown>;
  },
) {
  const threadId = runStreamThreadId(route);
  const responseMessage = options?.responseMessage ?? {
    type: "ai",
    id: "msg-ai-1",
    content: "Hello from DeerFlow!",
  };
  const events = [
    {
      event: "metadata",
      data: { run_id: MOCK_RUN_ID, thread_id: threadId },
    },
    ...(options?.messageMetadata
      ? [
          {
            event: "messages",
            data: [responseMessage, options.messageMetadata],
          },
        ]
      : []),
    {
      event: "values",
      data: {
        ...values,
        messages: mockStreamMessages(route, inputMessages, responseMessage),
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
