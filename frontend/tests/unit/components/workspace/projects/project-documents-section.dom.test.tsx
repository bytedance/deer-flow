import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";

// Hoisted hook doubles: the section reads everything through the projects
// barrel, so the mock swaps data stores instead of the network.
const mocks = rs.hoisted(() => {
  class MockContentMissingError extends Error {
    constructor() {
      super("content_missing");
      this.name = "ProjectDocumentContentMissingError";
    }
  }
  return {
    documents: [] as ProjectDocument[],
    documentsTotal: 0,
    documentsHasNextPage: false,
    documentsLoading: false,
    projectsConfig: {
      instructions_max_bytes: 8192,
      trash_retention_days: 30,
    } as
      | { instructions_max_bytes: number; trash_retention_days: number }
      | undefined,
    fetchNextDocumentsPage: rs.fn(),
    threadFileGroups: [] as ProjectThreadFileGroup[],
    threadFilesParams: undefined as unknown,
    threadFilesHasNextPage: false,
    fetchNextThreadFilesPage: rs.fn(),
    uploadMutateAsync: rs.fn(async () => {
      throw new Error("not implemented");
    }),
    deleteMutate: rs.fn(),
    attachMutate: rs.fn(),
    promoteMutate: rs.fn(),
    fetchPreview:
      rs.fn<
        (
          projectId: string,
          documentId: string,
        ) => Promise<ProjectDocumentPreview>
      >(),
    threadsPages: [] as AgentThread[][],
    threadsHasNextPage: false,
    threadsLoading: false,
    fetchNextThreadsPage: rs.fn(),
    infiniteThreadsParams: undefined as unknown,
    MockContentMissingError,
  };
});

rs.mock("@/core/projects", () => {
  // Stable identities across renders: the section's accumulate-pages effect
  // keys on ``data`` identity, so a fresh object per call would render-loop.
  const documentsResult = {
    data: {
      pages: [
        {
          documents: [] as ProjectDocument[],
          total: 0,
          limit: 100,
          offset: 0,
        },
      ],
    },
    isLoading: false,
    isError: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: mocks.fetchNextDocumentsPage,
    refetch: rs.fn(),
  };
  const threadFilesResult = {
    data: {
      pages: [
        {
          groups: [] as ProjectThreadFileGroup[],
          next_offset: null as number | null,
          truncated: false,
        },
      ],
    },
    isLoading: false,
    isError: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: mocks.fetchNextThreadFilesPage,
    refetch: rs.fn(),
  };
  return {
    PROJECTS_CONFIG_DEFAULT: {
      instructions_max_bytes: 8192,
      trash_retention_days: 30,
    },
    useProjectsConfig: () => ({ data: mocks.projectsConfig }),
    useInfiniteProjectDocuments: () => {
      documentsResult.data.pages[0]!.documents = mocks.documents;
      documentsResult.data.pages[0]!.total = mocks.documentsTotal;
      documentsResult.isLoading = mocks.documentsLoading;
      documentsResult.hasNextPage = mocks.documentsHasNextPage;
      return documentsResult;
    },
    useInfiniteProjectThreadFiles: (projectId: string, params: unknown) => {
      mocks.threadFilesParams = params;
      threadFilesResult.data.pages[0]!.groups = mocks.threadFileGroups;
      threadFilesResult.hasNextPage = mocks.threadFilesHasNextPage;
      return threadFilesResult;
    },
    useUploadProjectDocument: () => ({
      mutateAsync: mocks.uploadMutateAsync,
      isPending: false,
    }),
    useDeleteProjectDocument: () => ({
      mutate: mocks.deleteMutate,
      isPending: false,
    }),
    useAttachProjectDocument: () => ({
      mutate: mocks.attachMutate,
      isPending: false,
    }),
    usePromoteThreadFile: () => ({
      mutate: mocks.promoteMutate,
      isPending: false,
    }),
    fetchProjectDocumentPreview: mocks.fetchPreview,
    ProjectDocumentContentMissingError: mocks.MockContentMissingError,
    urlOfProjectDocumentContent: (
      projectId: string,
      documentId: string,
      { download = false }: { download?: boolean } = {},
    ) =>
      `/backend/api/projects/${projectId}/documents/${documentId}/content${download ? "?download=true" : ""}`,
  };
});

rs.mock("@/core/threads/hooks", () => ({
  useInfiniteThreads: (params: unknown) => {
    mocks.infiniteThreadsParams = params;
    return {
      data: { pages: mocks.threadsPages },
      isLoading: mocks.threadsLoading,
      hasNextPage: mocks.threadsHasNextPage,
      isFetchingNextPage: false,
      fetchNextPage: mocks.fetchNextThreadsPage,
    };
  },
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
}));

// The real preview pulls Streamdown/KaTeX into the worker bundle (several GB
// under rstest); the shelf tests only need the byte formatter and an inert
// preview body.
rs.mock("@/components/workspace/artifacts/artifact-file-preview", () => ({
  ArtifactFilePreview: () => null,
  formatArtifactBytes: (bytes: number | undefined) => {
    if (bytes === undefined) return undefined;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  },
}));

rs.mock("next/link", () => {
  const MockLink = ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>;
  return { default: MockLink };
});

import { ProjectDocumentsSection } from "@/components/workspace/projects/project-documents-section";
import { I18nProvider } from "@/core/i18n/context";
import type { ProjectDocumentPreview } from "@/core/projects/api";
import type {
  Project,
  ProjectDocument,
  ProjectThread,
  ProjectThreadFileGroup,
} from "@/core/projects/types";
import type { AgentThread } from "@/core/threads/types";

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

function makeProject(status: "active" | "archived" = "active"): Project {
  return {
    id: "proj-1",
    name: "Alpha",
    instructions: "",
    presentation: {},
    status,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };
}

function makeDocument(
  overrides: Partial<ProjectDocument> = {},
): ProjectDocument {
  return {
    id: "doc-1",
    name: "roadmap.md",
    size_bytes: 2048,
    sha256: "abc",
    content_missing: false,
    source_thread_id: null,
    source_kind: null,
    source_name: null,
    created_at: "2026-09-10T00:00:00Z",
    updated_at: "2026-09-10T00:00:00Z",
    ...overrides,
  };
}

const THREADS: ProjectThread[] = [
  {
    thread_id: "thread-9",
    display_name: "Report chat",
    metadata: {},
    created_at: "2026-09-09T00:00:00Z",
    updated_at: "2026-09-09T00:00:00Z",
  },
];

function makeAgentThread(overrides: Record<string, unknown> = {}): AgentThread {
  return {
    thread_id: "thread-a",
    values: { title: "Chat" },
    metadata: {},
    created_at: "2026-09-09T00:00:00Z",
    updated_at: "2026-09-09T00:00:00Z",
    ...overrides,
  } as AgentThread;
}

beforeEach(() => {
  mocks.documents = [];
  mocks.documentsTotal = 0;
  mocks.documentsHasNextPage = false;
  mocks.projectsConfig = {
    instructions_max_bytes: 8192,
    trash_retention_days: 30,
  };
  mocks.threadFileGroups = [];
  mocks.threadFilesHasNextPage = false;
  mocks.threadsPages = [];
  mocks.threadsHasNextPage = false;
  mocks.threadsLoading = false;
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("ProjectDocumentsSection", () => {
  it("renders shelf rows with the provenance badge for thread-sourced documents", () => {
    mocks.documents = [
      makeDocument({
        id: "doc-out",
        name: "summary.pdf",
        source_thread_id: "thread-9",
        source_kind: "output",
        source_name: "summary.pdf",
      }),
      makeDocument({ id: "doc-up", name: "notes.txt" }),
    ];
    render(
      <ProjectDocumentsSection project={makeProject()} threads={THREADS} />,
      { wrapper: Wrapper },
    );
    expect(screen.getByText("summary.pdf")).toBeDefined();
    expect(screen.getAllByText(/2\.0 KiB/).length).toBeGreaterThan(0);
    expect(screen.getByText("from Report chat · output")).toBeDefined();
    // Upload-sourced rows carry no provenance badge: exactly one badge total.
    expect(screen.getByText("notes.txt")).toBeDefined();
    expect(screen.getAllByText(/from Report chat/)).toHaveLength(1);
  });

  it("shows the empty state with the interim memory notice", () => {
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    expect(screen.getByText("No documents yet")).toBeDefined();
    expect(screen.getByText(/Memory stays global for now/)).toBeDefined();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDefined();
  });

  it("renders a content-missing row from the server flag without any preview attempt", () => {
    mocks.documents = [makeDocument({ content_missing: true })];
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    // The list response's ``content_missing`` flag is authoritative: badge +
    // trash-only action render immediately, no preview fetch is probed.
    expect(screen.getByTestId("content-missing-badge")).toBeDefined();
    expect(screen.getByText("Content missing")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Attach to chat/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Move to trash/ })).toBeDefined();
    expect(mocks.fetchPreview).not.toHaveBeenCalled();
  });

  it("shows the in-dialog error when a healthy row's preview answers 409", async () => {
    mocks.documents = [makeDocument()];
    mocks.fetchPreview.mockRejectedValue(new mocks.MockContentMissingError());
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => {
      expect(
        within(dialog).getByText("Couldn't load project documents"),
      ).toBeDefined();
    });
    // The row is NOT marked missing from a failed preview: the server flag
    // on the next list response owns that state. (Close the modal first —
    // it hides the shelf from the accessibility tree.)
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(screen.queryByTestId("content-missing-badge")).toBeNull();
    expect(screen.getByRole("button", { name: "Preview" })).toBeDefined();
  });

  it("shows the archived read-only banner and hides every mutation affordance", () => {
    mocks.documents = [makeDocument()];
    mocks.threadFileGroups = [
      {
        thread_id: "thread-9",
        display_name: "Report chat",
        updated_at: "2026-09-09T00:00:00Z",
        truncated: false,
        files: [
          {
            kind: "output",
            name: "chart.png",
            size_bytes: 1024,
            modified_at: "2026-09-09T00:00:00Z",
            artifact_url:
              "/api/threads/thread-9/artifacts/mnt/user-data/outputs/chart.png",
          },
        ],
      },
    ];
    render(
      <ProjectDocumentsSection
        project={makeProject("archived")}
        threads={THREADS}
      />,
      { wrapper: Wrapper },
    );
    expect(
      screen.getByTestId("project-documents-archived-banner"),
    ).toBeDefined();
    // Reads stay: preview, download, attach.
    expect(screen.getByRole("button", { name: "Preview" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Download" })).toBeDefined();
    expect(
      screen.getByRole("button", { name: /Attach to chat/ }),
    ).toBeDefined();
    // Mutations go: upload, trash, save-to-project.
    expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Move to trash/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Save to project" }),
    ).toBeNull();
  });

  it("offers Save to project with a shelf-name default for active projects", () => {
    mocks.threadFileGroups = [
      {
        thread_id: "thread-9",
        display_name: "Report chat",
        updated_at: "2026-09-09T00:00:00Z",
        truncated: false,
        files: [
          {
            kind: "output",
            name: "chart.png",
            size_bytes: 1024,
            modified_at: "2026-09-09T00:00:00Z",
            artifact_url:
              "/api/threads/thread-9/artifacts/mnt/user-data/outputs/chart.png",
          },
        ],
      },
    ];
    render(
      <ProjectDocumentsSection project={makeProject()} threads={THREADS} />,
      { wrapper: Wrapper },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save to project" }));
    const input = screen.getByLabelText("Shelf name");
    expect(input).toHaveProperty("value", "chart.png");
  });
  it("paginates the shelf: loaded-vs-total plus a Load more that fetches the next page", () => {
    mocks.documents = [
      makeDocument({ id: "doc-1", name: "a.txt" }),
      makeDocument({ id: "doc-2", name: "b.txt" }),
      makeDocument({ id: "doc-3", name: "c.txt" }),
    ];
    mocks.documentsTotal = 5;
    mocks.documentsHasNextPage = true;
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    expect(screen.getByText("Showing 3 of 5")).toBeDefined();
    fireEvent.click(screen.getByTestId("project-documents-load-more"));
    expect(mocks.fetchNextDocumentsPage).toHaveBeenCalledTimes(1);
  });

  it("hides Load more once every shelf row is loaded", () => {
    mocks.documents = [makeDocument()];
    mocks.documentsTotal = 1;
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    expect(screen.getByText("Showing 1 of 1")).toBeDefined();
    expect(screen.queryByTestId("project-documents-load-more")).toBeNull();
  });

  it("names the configured retention window in the move-to-trash confirmation", () => {
    mocks.projectsConfig = {
      instructions_max_bytes: 8192,
      trash_retention_days: 7,
    };
    mocks.documents = [makeDocument()];
    mocks.documentsTotal = 1;
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: /Move to trash/ }));
    expect(screen.getByText(/stay recoverable for 7 days/)).toBeDefined();
  });

  it("falls back to the 30-day default when the config endpoint is unavailable", () => {
    mocks.projectsConfig = undefined;
    mocks.documents = [makeDocument()];
    mocks.documentsTotal = 1;
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: /Move to trash/ }));
    expect(screen.getByText(/stay recoverable for 30 days/)).toBeDefined();
  });

  it("renders a browser-viewable binary in the sandboxed iframe, never as text", async () => {
    mocks.documents = [makeDocument({ id: "doc-img", name: "chart.png" })];
    mocks.fetchPreview.mockResolvedValue({ kind: "binary" });
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const frame = await screen.findByTestId("project-document-preview-frame");
    expect(frame.getAttribute("src")).toBe(
      "/backend/api/projects/proj-1/documents/doc-img/content",
    );
    expect(frame.getAttribute("sandbox")).toBe("");
  });

  it("renders a PDF inline without the sandbox attribute, with download and open-in-new-tab actions", async () => {
    mocks.documents = [makeDocument({ id: "doc-pdf", name: "slides.pdf" })];
    mocks.fetchPreview.mockResolvedValue({ kind: "pdf" });
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const dialog = await screen.findByRole("dialog");
    // The unified PDF mechanism: an iframe WITHOUT sandbox (Chromium blocks
    // its built-in viewer inside sandbox=""), same as the artifact detail
    // view.
    const frame = within(dialog).getByTestId("project-document-preview-frame");
    expect(frame.getAttribute("src")).toBe(
      "/backend/api/projects/proj-1/documents/doc-pdf/content",
    );
    expect(frame.getAttribute("sandbox")).toBeNull();
    const openTab = within(dialog).getByTestId(
      "project-document-preview-open-tab",
    );
    expect(openTab.getAttribute("href")).toBe(
      "/backend/api/projects/proj-1/documents/doc-pdf/content",
    );
    expect(openTab.getAttribute("target")).toBe("_blank");
    const download = within(dialog).getByRole("link", { name: "Download" });
    expect(download.getAttribute("href")).toBe(
      "/backend/api/projects/proj-1/documents/doc-pdf/content?download=true",
    );
  });

  it("shows the truncation notice and full-file action for oversized text previews", async () => {
    mocks.documents = [
      makeDocument({ id: "doc-big", name: "big.md", size_bytes: 52428800 }),
    ];
    mocks.fetchPreview.mockResolvedValue({
      kind: "text",
      content: "# prefix",
      truncated: true,
      previewBytes: 1048576,
      totalBytes: 52428800,
    });
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const banner = await screen.findByTestId(
      "project-document-preview-truncated",
    );
    expect(banner.textContent).toContain(
      "Showing the first 1.0 MiB of 50.0 MiB.",
    );
    const fullFile = screen.getByRole("link", { name: "Load full file" });
    expect(fullFile.getAttribute("href")).toBe(
      "/backend/api/projects/proj-1/documents/doc-big/content",
    );
  });

  it("shows the unsupported-preview fallback with a download action", async () => {
    mocks.documents = [makeDocument({ id: "doc-zip", name: "archive.zip" })];
    mocks.fetchPreview.mockResolvedValue({ kind: "unsupported" });
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(
        "This file type can't be previewed in the browser. Download it to view it.",
      ),
    ).toBeDefined();
    const download = within(dialog).getByRole("link", { name: "Download" });
    expect(download.getAttribute("href")).toBe(
      "/backend/api/projects/proj-1/documents/doc-zip/content?download=true",
    );
  });

  it("renders an untruncated text preview without the notice", async () => {
    mocks.documents = [makeDocument({ id: "doc-md", name: "notes.md" })];
    mocks.fetchPreview.mockResolvedValue({
      kind: "text",
      content: "# hi",
      truncated: false,
      previewBytes: 4,
      totalBytes: 4,
    });
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("dialog");
    await waitFor(() => {
      expect(mocks.fetchPreview).toHaveBeenCalledWith("proj-1", "doc-md");
    });
    expect(
      screen.queryByTestId("project-document-preview-truncated"),
    ).toBeNull();
  });

  it("attach picker asks for non-archived threads server-side and pages with Load more", async () => {
    mocks.documents = [makeDocument()];
    mocks.threadsPages = [
      [
        makeAgentThread({
          thread_id: "thread-active",
          values: { title: "Active chat" },
        }),
        makeAgentThread({
          thread_id: "thread-archived",
          values: { title: "Archived chat" },
          metadata: { deerflow_archived: true },
        }),
      ],
    ];
    mocks.threadsHasNextPage = true;
    render(<ProjectDocumentsSection project={makeProject()} threads={[]} />, {
      wrapper: Wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: /Attach to chat/ }));
    const dialog = await screen.findByRole("dialog");
    // Archived chats are requested away server-side and filtered again
    // client-side, so one never occupies an eligible slot.
    expect(mocks.infiniteThreadsParams).toMatchObject({ archived: false });
    expect(within(dialog).getByText("Active chat")).toBeDefined();
    expect(within(dialog).queryByText("Archived chat")).toBeNull();
    fireEvent.click(screen.getByTestId("attach-thread-load-more"));
    expect(mocks.fetchNextThreadsPage).toHaveBeenCalledTimes(1);
  });

  it("flags a truncated thread group, requests the API max file limit, and links to the thread", () => {
    mocks.threadFileGroups = [
      {
        thread_id: "thread-9",
        display_name: "Report chat",
        updated_at: "2026-09-09T00:00:00Z",
        truncated: true,
        files: [
          {
            kind: "upload",
            name: "notes.txt",
            size_bytes: 64,
            modified_at: "2026-09-09T00:00:00Z",
            artifact_url:
              "/api/threads/thread-9/artifacts/mnt/user-data/uploads/notes.txt",
          },
          {
            kind: "output",
            name: "chart.png",
            size_bytes: 1024,
            modified_at: "2026-09-09T00:00:00Z",
            artifact_url:
              "/api/threads/thread-9/artifacts/mnt/user-data/outputs/chart.png",
          },
        ],
      },
    ];
    render(
      <ProjectDocumentsSection project={makeProject()} threads={THREADS} />,
      { wrapper: Wrapper },
    );
    // The query asks for the API's maximum per-thread cap to minimize cuts.
    expect(mocks.threadFilesParams).toMatchObject({ file_limit: 200 });
    const notice = screen.getByTestId("thread-files-truncated");
    expect(notice.textContent).toContain(
      "Only the first 2 files of this chat are shown.",
    );
    const link = within(notice).getByRole("link", {
      name: "Browse all files in the chat",
    });
    expect(link.getAttribute("href")).toBe("/workspace/chats/thread-9");
    // Listed rows keep their save-to-project action.
    expect(
      screen.getAllByRole("button", { name: "Save to project" }),
    ).toHaveLength(2);
  });

  it("renders no truncation notice for a complete thread group", () => {
    mocks.threadFileGroups = [
      {
        thread_id: "thread-9",
        display_name: "Report chat",
        updated_at: "2026-09-09T00:00:00Z",
        truncated: false,
        files: [
          {
            kind: "output",
            name: "chart.png",
            size_bytes: 1024,
            modified_at: "2026-09-09T00:00:00Z",
            artifact_url:
              "/api/threads/thread-9/artifacts/mnt/user-data/outputs/chart.png",
          },
        ],
      },
    ];
    render(
      <ProjectDocumentsSection project={makeProject()} threads={THREADS} />,
      { wrapper: Wrapper },
    );
    expect(screen.getByText("chart.png")).toBeDefined();
    expect(screen.queryByTestId("thread-files-truncated")).toBeNull();
  });

  it.each([
    ["null", null],
    ["missing", undefined],
    ["blank", "   "],
  ])(
    "labels a thread group whose title is %s as Untitled instead of rendering an empty heading",
    (_label, displayName) => {
      // ``display_name`` is nullable on the wire: the thread meta row starts
      // as ``null`` and is only filled once title generation has run.
      mocks.threadFileGroups = [
        {
          thread_id: "thread-9",
          display_name: displayName,
          updated_at: "2026-09-09T00:00:00Z",
          truncated: false,
          files: [
            {
              kind: "output",
              name: "chart.png",
              size_bytes: 1024,
              modified_at: "2026-09-09T00:00:00Z",
              artifact_url:
                "/api/threads/thread-9/artifacts/mnt/user-data/outputs/chart.png",
            },
          ],
        },
      ];
      render(
        <ProjectDocumentsSection project={makeProject()} threads={THREADS} />,
        { wrapper: Wrapper },
      );
      expect(screen.getByText("Untitled")).toBeDefined();
    },
  );
});
