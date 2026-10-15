import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, expect, it, rs } from "@rstest/core";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  waitFor,
} from "@testing-library/react";
import { useEffect } from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { Sheet } from "@/components/ui/sheet";
import { SidebarProvider } from "@/components/ui/sidebar";
import { ArtifactFilePreview } from "@/components/workspace/artifacts/artifact-file-preview";
import { ArtifactsProvider } from "@/components/workspace/artifacts/context";
import { BrowserViewPanel } from "@/components/workspace/browser-view/browser-view-panel";
import {
  BrowserViewProvider,
  useBrowserView,
} from "@/components/workspace/browser-view/context";
import { WorkspaceChangePanel } from "@/components/workspace/changes/workspace-change-panel";
import { ThreadContext } from "@/components/workspace/messages/context";
import { MessageGroup } from "@/components/workspace/messages/message-group";
import { MessageListItem } from "@/components/workspace/messages/message-list-item";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  useWorkspaceLifetime,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

const mocks = rs.hoisted(() => ({ threadId: "thread-1" }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
  usePathname: () => `/workspace/chats/${mocks.threadId}`,
  useSearchParams: () => new URLSearchParams(),
}));
// This gate exercises static screenshot URLs, not the separate Live/WSS protocol.
rs.mock("@/components/workspace/browser-view/use-browser-stream", () => ({
  useBrowserStream: () => ({
    status: "idle",
    frameUrl: null,
    liveUrl: null,
    tabs: [],
    sendInput: () => false,
  }),
}));
const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
const THREAD = "thread-1";
const CHART = "/mnt/user-data/outputs/chart.png";
const summary = {
  created: 1,
  modified: 0,
  deleted: 0,
  symlink_created: 0,
  additions: 1,
  deletions: 0,
  truncated: false,
};
type Seen = {
  path: string;
  workspace: string | null;
  method: string;
  body: unknown;
  signal?: AbortSignal | null;
};
function fixture(
  options: {
    intercept?: (row: Seen, response: Response) => Response;
    deleteStatus?: number;
  } = {},
) {
  const seen: Seen[] = [];
  rs.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        location.href,
      );
      const workspace = new Headers(init?.headers).get("X-Deerflow-Workspace");
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as unknown)
          : null;
      const row: Seen = {
        path: url.pathname,
        workspace,
        method,
        body,
        signal: init?.signal,
      };
      seen.push(row);
      const reply = (response: Response) =>
        options.intercept?.(row, response) ?? response;
      const currentThread = url.pathname.split("/")[3] ?? THREAD;
      if (url.pathname === "/api/workspaces")
        return Response.json(
          [P, T].map((id) => ({
            id,
            name: id,
            kind: id === P ? "personal" : "team",
            personal_user_id: id === P ? "alice" : null,
            status: "active",
            role: "owner",
            membership_version: 1,
            policy_version: 1,
          })),
        );
      if (url.pathname === "/api/workspaces/current")
        return Response.json({
          actor_user_id: "alice",
          workspace_id: workspace,
          membership_version: 1,
          policy_version: 1,
        });
      if (url.pathname.endsWith("/workspace-changes"))
        return reply(
          Response.json({
            available: true,
            version: 1,
            summary,
            files: [
              {
                path: `/mnt/user-data/outputs/change-${workspace}-${currentThread}.txt`,
                root: "outputs",
                status: "created",
                binary: false,
                sensitive: false,
                size_before: null,
                size_after: 3,
                sha256_before: null,
                sha256_after: "a".repeat(64),
                diff: "+new",
                diff_truncated: false,
                diff_unavailable_reason: null,
                additions: 1,
                deletions: 0,
                symlink: false,
                symlink_target_before: null,
                symlink_target_after: null,
              },
            ],
            limits: {},
          }),
        );
      if (url.pathname.endsWith("/feedback"))
        return reply(
          method === "DELETE"
            ? new Response(null, { status: options.deleteStatus ?? 204 })
            : Response.json({
                feedback_id: `feedback-${workspace}`,
                rating: 1,
                comment: null,
              }),
        );
      throw new Error(
        `Unexpected resource-surface request ${method} ${url.pathname}`,
      );
    },
  );
  return seen;
}
function mount(options: { reportContent?: string } = {}) {
  let controls: WorkspaceContextValue | null = null;
  let cache: QueryClient | null = null;
  let lifetime: ReturnType<typeof useWorkspaceLifetime> = null;
  function Controls() {
    controls = useWorkspaceContext();
    return null;
  }
  function Surfaces() {
    const threadId = mocks.threadId;
    cache = useQueryClient();
    lifetime = useWorkspaceLifetime();
    const { pushFrame } = useBrowserView();
    useEffect(() => {
      pushFrame({
        screenshot: "/mnt/user-data/outputs/screen.png",
        title: "Static screenshot",
        url: "https://example.test",
      });
    }, [pushFrame]);
    const tool: Message[] = [
      {
        type: "ai",
        id: "tool-ai",
        content: "",
        tool_calls: [{ id: "shot", name: "browser_screenshot", args: {} }],
      },
      {
        type: "tool",
        id: "tool-result",
        tool_call_id: "shot",
        content: "done",
        additional_kwargs: {
          browser_view: {
            screenshot: "/mnt/user-data/outputs/tool.png",
            title: "Tool screenshot",
          },
        },
      },
    ];
    return (
      <ThreadContext.Provider
        value={{
          thread: { messages: [], isLoading: false } as never,
          isMock: false,
        }}
      >
        <MessageListItem
          threadId={threadId}
          showCopyButton={false}
          artifactPaths={[CHART]}
          message={{
            type: "ai",
            id: "answer",
            content: `[Message report](/mnt/user-data/outputs/report.md?download=true#section) ![Message chart](chart.png) [External reference](https://example.test/source) [citation:Message evidence](/mnt/user-data/outputs/evidence.txt?download=true#evidence) [citation:Raw evidence](${location.origin}/api/threads/${threadId}/artifacts/mnt/user-data/outputs/raw-evidence.txt?workspace_id=${T})`,
          }}
        />
        <MessageListItem
          threadId={threadId}
          showCopyButton={false}
          message={{
            type: "human",
            id: "upload",
            content: "Uploaded image",
            additional_kwargs: {
              files: [
                {
                  filename: "input.png",
                  path: "/mnt/user-data/uploads/input.png",
                  size: 3,
                  status: "uploaded",
                },
              ],
            },
          }}
        />
        <div data-testid="feedback-row">
          <MessageListItem
            threadId={threadId}
            runId="run-1"
            feedback={null}
            message={{
              type: "ai",
              id: "feedback-answer",
              content: "Rate this answer",
            }}
          />
        </div>
        <ArtifactFilePreview
          language="markdown"
          scrollKey="report"
          url={urlOfArtifact({
            threadId,
            filepath: "/mnt/user-data/outputs/reports/report.md",
          })}
          content={
            options.reportContent ??
            `# Source report
[Appendix](../appendix.md?download=true#method)
![Report evidence](../evidence.png)
[Owned file](/mnt/user-data/outputs/owned.txt?workspace_id=${P}#owned)`
          }
        />
        <MessageGroup threadId={threadId} messages={tool} />
        <BrowserViewPanel threadId={threadId} />
        <Sheet open modal={false}>
          <WorkspaceChangePanel
            threadId={threadId}
            runId="run-1"
            fallbackSummary={summary}
            open
          />
        </Sheet>
      </ThreadContext.Provider>
    );
  }
  const tree = () => (
    <AuthProvider
      initialUser={{
        id: "alice",
        email: "alice@example.test",
        system_role: "user",
        needs_setup: false,
      }}
    >
      <QueryClientProvider>
        <I18nContext.Provider
          value={{ locale: "en-US", t: enUS, setLocale: () => undefined }}
        >
          <WorkspaceProvider enabled>
            <Controls />
            <WorkspaceReadyBoundary>
              <SidebarProvider>
                <ArtifactsProvider>
                  <BrowserViewProvider>
                    <Surfaces />
                  </BrowserViewProvider>
                </ArtifactsProvider>
              </SidebarProvider>
            </WorkspaceReadyBoundary>
          </WorkspaceProvider>
        </I18nContext.Provider>
      </QueryClientProvider>
    </AuthProvider>
  );
  const view = render(tree());
  return {
    view,
    cache: () => cache!,
    lifetime: () => lifetime!,
    route: (threadId: string) => {
      mocks.threadId = threadId;
      view.rerender(tree());
    },
    select: async (id: string) => {
      await act(async () => {
        expect(await controls!.select(id)).toBe(true);
      });
    },
  };
}
function resource(value: string | null, workspace: string, path: string) {
  expect(value).not.toBeNull();
  const url = new URL(value!, location.href);
  expect(url.searchParams.get("workspace_id")).toBe(workspace);
  expect(url.pathname).toBe(`/api/threads/${THREAD}/artifacts${path}`);
  return url;
}
function thumb(app: ReturnType<typeof mount>) {
  const button = app.view
    .getByTestId("feedback-row")
    .querySelector("svg.lucide-thumbs-up")
    ?.closest("button");
  if (!(button instanceof HTMLButtonElement))
    throw new Error("Feedback control missing");
  return button;
}
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  rs.restoreAllMocks();
  mocks.threadId = "thread-1";
});
it("binds the real message, report, screenshot, feedback and file-change main path to each workspace", async () => {
  const seen = fixture();
  const app = mount();
  for (const workspace of [P, T]) {
    if (workspace === T) await app.select(T);
    const report = await app.view.findByRole("link", {
      name: "Message report",
    });
    const url = resource(
      report.getAttribute("href"),
      workspace,
      "/mnt/user-data/outputs/report.md",
    );
    expect(url.searchParams.get("download")).toBe("true");
    expect(url.hash).toBe("#section");
    const evidence = resource(
      app.view
        .getByRole("link", { name: "Message evidence" })
        .getAttribute("href"),
      workspace,
      "/mnt/user-data/outputs/evidence.txt",
    );
    expect(evidence.searchParams.get("download")).toBe("true");
    expect(evidence.hash).toBe("#evidence");
    resource(
      app.view.getByRole("link", { name: "Raw evidence" }).getAttribute("href"),
      workspace,
      "/mnt/user-data/outputs/raw-evidence.txt",
    );
    resource(
      app.view.getByRole("img", { name: "Message chart" }).getAttribute("src"),
      workspace,
      CHART,
    );
    resource(
      app.view.getByRole("img", { name: "input.png" }).getAttribute("src"),
      workspace,
      "/mnt/user-data/uploads/input.png",
    );
    const appendix = resource(
      app.view.getByRole("link", { name: "Appendix" }).getAttribute("href"),
      workspace,
      "/mnt/user-data/outputs/appendix.md",
    );
    expect(appendix.searchParams.get("download")).toBe("true");
    expect(appendix.hash).toBe("#method");
    expect(
      app.view
        .getByRole("img", { name: "Report evidence" })
        .getAttribute("data-streamdown"),
    ).toBe("image");
    expect(
      app.view
        .getByRole("img", { name: "Report evidence" })
        .closest('[data-streamdown="image-wrapper"]'),
    ).toBeTruthy();
    resource(
      app.view
        .getByRole("img", { name: "Report evidence" })
        .getAttribute("src"),
      workspace,
      "/mnt/user-data/outputs/evidence.png",
    );
    resource(
      app.view.getByRole("link", { name: "Owned file" }).getAttribute("href"),
      workspace,
      "/mnt/user-data/outputs/owned.txt",
    );
    resource(
      app.view
        .getByRole("img", { name: "Tool screenshot" })
        .getAttribute("src"),
      workspace,
      "/mnt/user-data/outputs/tool.png",
    );
    resource(
      app.view
        .getByRole("img", { name: "Static screenshot" })
        .getAttribute("src"),
      workspace,
      "/mnt/user-data/outputs/screen.png",
    );
    await waitFor(() =>
      resource(
        app.view
          .getByRole("link", { name: enUS.workspaceChanges.openFile })
          .getAttribute("href"),
        workspace,
        `/mnt/user-data/outputs/change-${workspace}-${THREAD}.txt`,
      ),
    );
    expect(
      app.view
        .getByRole("link", { name: "External reference" })
        .getAttribute("href"),
    ).toBe("https://example.test/source");
    fireEvent.click(thumb(app));
    await waitFor(() =>
      expect(
        thumb(app).querySelector("svg")?.classList.contains("fill-current"),
      ).toBe(true),
    );
    fireEvent.click(thumb(app));
    await waitFor(() =>
      expect(
        thumb(app).querySelector("svg")?.classList.contains("fill-current"),
      ).toBe(false),
    );
  }
  expect(
    seen
      .filter((row) => row.path.endsWith("/workspace-changes"))
      .map((row) => row.workspace),
  ).toEqual([P, T]);
  expect(
    seen
      .filter((row) => row.path.endsWith("/feedback"))
      .map((row) => [row.workspace, row.method, row.body]),
  ).toEqual([
    [P, "PUT", { rating: 1, comment: null }],
    [P, "DELETE", null],
    [T, "PUT", { rating: 1, comment: null }],
    [T, "DELETE", null],
  ]);
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
it("keeps replacement feedback pending and new file changes intact when old same-space bodies finish", async () => {
  const oldVote = deferred<void>(),
    newVote = deferred<void>(),
    oldChanges = deferred<void>();
  const enteredVote = deferred<void>(),
    enteredNewVote = deferred<void>(),
    enteredChanges = deferred<void>();
  const decodedVote = deferred<void>(),
    decodedChanges = deferred<void>();
  const seen = fixture({
    deleteStatus: 404,
    intercept: (row, response) => {
      if (
        row.path.includes("/thread-1/") &&
        (row.path.endsWith("/workspace-changes") || row.method === "PUT")
      ) {
        const vote = row.method === "PUT";
        const decode = response.json.bind(response);
        rs.spyOn(response, "json").mockImplementation(async () => {
          (vote ? enteredVote : enteredChanges).resolve();
          await (vote ? oldVote : oldChanges).promise;
          const value: unknown = await decode();
          (vote ? decodedVote : decodedChanges).resolve();
          return value;
        });
      }
      if (row.path.includes("/thread-2/") && row.method === "PUT") {
        const decode = response.json.bind(response);
        rs.spyOn(response, "json").mockImplementation(async () => {
          enteredNewVote.resolve();
          await newVote.promise;
          return decode() as Promise<unknown>;
        });
      }
      return response;
    },
  });
  const app = mount();
  await enteredChanges.promise;
  await app.view.findByRole("link", { name: "Message report" });
  const life = app.lifetime();
  const cache = app.cache();
  fireEvent.click(thumb(app));
  await enteredVote.promise;
  app.route("thread-2");
  await waitFor(() =>
    expect(
      app.view
        .getByRole("link", { name: enUS.workspaceChanges.openFile })
        .getAttribute("href"),
    ).toContain(`change-${P}-thread-2.txt`),
  );
  expect(app.lifetime()).toBe(life);
  expect(app.cache()).toBe(cache);
  expect(life.scope.signal.aborted).toBe(false);
  fireEvent.click(thumb(app));
  await enteredNewVote.promise;
  expect(thumb(app).disabled).toBe(true);
  await act(async () => {
    oldVote.resolve();
    oldChanges.resolve();
    await Promise.all([decodedVote.promise, decodedChanges.promise]);
  });
  expect(thumb(app).disabled).toBe(true);
  expect(
    thumb(app).querySelector("svg")?.classList.contains("fill-current"),
  ).toBe(false);
  expect(
    seen.find(
      (row) =>
        row.path.includes("/thread-1/") &&
        row.path.endsWith("/workspace-changes"),
    )?.signal?.aborted,
  ).toBe(true);
  expect(
    cache.getQueryData(["workspace-changes", "thread-1", "run-1", true, true]),
  ).toBeUndefined();
  expect(
    app.view
      .getByRole("link", { name: enUS.workspaceChanges.openFile })
      .getAttribute("href"),
  ).toContain(`change-${P}-thread-2.txt`);
  await act(async () => {
    newVote.resolve();
  });
  await waitFor(() => expect(thumb(app).disabled).toBe(false));
  expect(
    thumb(app).querySelector("svg")?.classList.contains("fill-current"),
  ).toBe(true);
  fireEvent.click(thumb(app));
  await waitFor(() =>
    expect(
      thumb(app).querySelector("svg")?.classList.contains("fill-current"),
    ).toBe(false),
  );
});
it("binds content-authored raw file URLs but omits escaped report paths and preserves web references", async () => {
  fixture();
  const raw = `${location.origin}/api/threads/${THREAD}/artifacts/mnt/user-data/outputs/raw.txt?download=true&workspace_id=${P}&workspace_id=${P}#source`;
  const app = mount({
    reportContent: `# Report part
[Raw file](${raw})
![Raw image](${raw.replace("raw.txt", "raw.png")})
[Escape](../../../../../../../../unbound.txt)
![Escape image](../../../../../../../../unbound.png)
[Literal percent](/mnt/user-data/outputs/a%2520b.txt)
[Local anchor](#report-part)
[Web source](https://example.test/source?workspace_id=${P})`,
  });
  await app.select(T);
  const url = resource(
    (await app.view.findByRole("link", { name: "Raw file" })).getAttribute(
      "href",
    ),
    T,
    "/mnt/user-data/outputs/raw.txt",
  );
  expect(url.searchParams.getAll("workspace_id")).toEqual([T]);
  expect(url.searchParams.get("download")).toBe("true");
  expect(url.hash).toBe("#source");
  resource(
    app.view.getByRole("img", { name: "Raw image" }).getAttribute("src"),
    T,
    "/mnt/user-data/outputs/raw.png",
  );
  expect(app.view.queryByRole("link", { name: "Escape" })).toBeNull();
  expect(app.view.getByText("Escape")).toBeTruthy();
  expect(app.view.queryByRole("img", { name: "Escape image" })).toBeNull();
  expect(
    app.view.container.querySelector('img[src*="unbound.png"]'),
  ).toBeNull();
  resource(
    app.view
      .getByRole("link", { name: "Literal percent" })
      .getAttribute("href"),
    T,
    "/mnt/user-data/outputs/a%2520b.txt",
  );
  expect(
    app.view.getByRole("link", { name: "Local anchor" }).getAttribute("href"),
  ).toMatch(/^#/);
  expect(
    app.view.getByRole("link", { name: "Web source" }).getAttribute("href"),
  ).toBe(`https://example.test/source?workspace_id=${P}`);
});
