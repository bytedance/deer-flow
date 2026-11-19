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

// Hoisted doubles for the trash/projects hooks the view reads through.
const mocks = rs.hoisted(() => {
  class MockTrashNotFoundError extends Error {
    constructor(message: string) {
      super(message);
      this.name = "TrashNotFoundError";
    }
  }
  class MockRestoreConflictError extends Error {
    constructor(
      message: string,
      readonly detail: string,
    ) {
      super(message);
      this.name = "RestoreConflictError";
    }
  }
  return {
    documents: [] as TrashDocument[],
    documentsTotal: null as number | null,
    documentsHasNextPage: false,
    retentionDays: 30 as number | undefined,
    activeProjects: [] as Project[],
    fetchNextTrashPage: rs.fn(),
    restoreMutate: rs.fn(),
    purgeMutate: rs.fn(),
    emptyMutate: rs.fn(),
    MockTrashNotFoundError,
    MockRestoreConflictError,
  };
});

rs.mock("@/core/trash", () => {
  // Stable identity across renders: the view flattens ``data.pages``.
  const trashResult = {
    data: {
      pages: [
        {
          documents: [] as TrashDocument[],
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
    fetchNextPage: mocks.fetchNextTrashPage,
    refetch: rs.fn(),
  };
  return {
    TrashNotFoundError: mocks.MockTrashNotFoundError,
    RestoreConflictError: mocks.MockRestoreConflictError,
    useInfiniteTrashDocuments: () => {
      trashResult.data.pages[0]!.documents = mocks.documents;
      trashResult.data.pages[0]!.total =
        mocks.documentsTotal ?? mocks.documents.length;
      trashResult.hasNextPage = mocks.documentsHasNextPage;
      return trashResult;
    },
    useRestoreDocument: () => ({
      mutate: mocks.restoreMutate,
      isPending: false,
    }),
    usePurgeDocument: () => ({
      mutate: mocks.purgeMutate,
      isPending: false,
    }),
    useEmptyTrash: () => ({
      mutate: mocks.emptyMutate,
      isPending: false,
    }),
  };
});

rs.mock("@/core/projects", () => ({
  PROJECTS_CONFIG_DEFAULT: {
    instructions_max_bytes: 8192,
    trash_retention_days: 30,
  },
  useProjectsConfig: () => ({
    data:
      mocks.retentionDays === undefined
        ? undefined
        : {
            instructions_max_bytes: 8192,
            trash_retention_days: mocks.retentionDays,
          },
  }),
  useProjects: () => ({
    data: mocks.activeProjects,
    isLoading: false,
  }),
}));

import { TrashView } from "@/components/workspace/trash/trash-view";
import { I18nProvider } from "@/core/i18n/context";
import type { Project } from "@/core/projects/types";
import type { TrashDocument } from "@/core/trash/types";

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

function makeTrashDocument(
  overrides: Partial<TrashDocument> = {},
): TrashDocument {
  return {
    id: "doc-1",
    name: "q3-report.pdf",
    size_bytes: 2048,
    sha256: "abc",
    content_missing: false,
    source_thread_id: null,
    source_kind: null,
    source_name: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    trashed_at: new Date(Date.now() - 10 * 86_400_000).toISOString(),
    trash_origin: { project_id: "proj-1", project_name: "Alpha" },
    ...overrides,
  };
}

beforeEach(() => {
  mocks.documents = [];
  mocks.documentsTotal = null;
  mocks.documentsHasNextPage = false;
  mocks.retentionDays = 30;
  mocks.activeProjects = [];
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("TrashView", () => {
  it("renders rows with the origin project and remaining retention", () => {
    mocks.documents = [makeTrashDocument()];
    render(<TrashView />, { wrapper: Wrapper });
    expect(screen.getByText("q3-report.pdf")).toBeDefined();
    expect(screen.getByText(/from Alpha/)).toBeDefined();
    expect(screen.getByText(/20 days left/)).toBeDefined();
    expect(screen.getByRole("button", { name: /Restore/ })).toBeDefined();
    expect(
      screen.getByRole("button", { name: /Delete permanently/ }),
    ).toBeDefined();
  });

  it("shows the empty state without the empty-trash action", () => {
    render(<TrashView />, { wrapper: Wrapper });
    expect(screen.getByText("Trash is empty.")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Empty trash" })).toBeNull();
  });

  it("offers the project picker when a targetless restore 404s, then retries with the picked project", async () => {
    mocks.documents = [makeTrashDocument()];
    mocks.activeProjects = [
      {
        id: "proj-2",
        name: "Beta",
        instructions: "",
        presentation: {},
        status: "active",
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
      },
    ];
    mocks.restoreMutate.mockImplementation(
      (
        input: { documentId: string; projectId?: string },
        options: {
          onError?: (error: Error) => void;
          onSuccess?: (result: unknown) => void;
        },
      ) => {
        if (input.projectId === undefined) {
          options.onError?.(
            new mocks.MockTrashNotFoundError("Trash document not found"),
          );
        }
      },
    );
    render(<TrashView />, { wrapper: Wrapper });
    fireEvent.click(screen.getByRole("button", { name: /Restore/ }));
    await waitFor(() => {
      expect(screen.getByText("Choose a project")).toBeDefined();
    });
    expect(
      screen.getByText(/original project is gone or archived/),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Beta" }));
    expect(mocks.restoreMutate).toHaveBeenLastCalledWith(
      { documentId: "doc-1", projectId: "proj-2" },
      expect.objectContaining({}),
    );
  });

  it("keeps the row and skips the picker on a content_missing restore conflict", async () => {
    mocks.documents = [makeTrashDocument()];
    mocks.restoreMutate.mockImplementation(
      (
        _input: { documentId: string },
        options: { onError?: (error: Error) => void },
      ) => {
        options.onError?.(
          new mocks.MockRestoreConflictError(
            "content_missing",
            "content_missing",
          ),
        );
      },
    );
    render(<TrashView />, { wrapper: Wrapper });
    fireEvent.click(screen.getByRole("button", { name: /Restore/ }));
    await waitFor(() => {
      expect(mocks.restoreMutate).toHaveBeenCalled();
    });
    // No picker for a conflict — the row simply stays in trash.
    expect(screen.queryByText("Choose a project")).toBeNull();
    expect(screen.getByText("q3-report.pdf")).toBeDefined();
  });

  it("requires the irreversible confirmation before purging one document", () => {
    mocks.documents = [makeTrashDocument()];
    mocks.purgeMutate.mockImplementation(
      (_id: string, options: { onSuccess?: () => void }) => {
        options.onSuccess?.();
      },
    );
    render(<TrashView />, { wrapper: Wrapper });
    fireEvent.click(screen.getByRole("button", { name: /Delete permanently/ }));
    expect(
      screen.getByText(/will be permanently deleted. This cannot be undone./),
    ).toBeDefined();
    expect(mocks.purgeMutate).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Delete permanently",
      }),
    );
    expect(mocks.purgeMutate).toHaveBeenCalledWith(
      "doc-1",
      expect.objectContaining({}),
    );
  });

  it("requires its own confirmation before emptying the trash", () => {
    mocks.documents = [makeTrashDocument(), makeTrashDocument({ id: "doc-2" })];
    render(<TrashView />, { wrapper: Wrapper });
    fireEvent.click(screen.getByTestId("trash-empty-button"));
    expect(
      screen.getByText(
        "2 documents will be permanently deleted. This cannot be undone.",
      ),
    ).toBeDefined();
    expect(mocks.emptyMutate).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Empty trash" }),
    );
    expect(mocks.emptyMutate).toHaveBeenCalled();
  });

  it("paginates: loaded-vs-total plus a Load more that fetches the next page", () => {
    mocks.documents = [makeTrashDocument()];
    mocks.documentsTotal = 3;
    mocks.documentsHasNextPage = true;
    render(<TrashView />, { wrapper: Wrapper });
    expect(screen.getByText("Showing 1 of 3")).toBeDefined();
    fireEvent.click(screen.getByTestId("trash-load-more"));
    expect(mocks.fetchNextTrashPage).toHaveBeenCalledTimes(1);
  });

  it("counts the server total, not just the loaded rows, in the empty-trash confirmation", () => {
    mocks.documents = [makeTrashDocument()];
    mocks.documentsTotal = 5;
    mocks.documentsHasNextPage = true;
    render(<TrashView />, { wrapper: Wrapper });
    fireEvent.click(screen.getByTestId("trash-empty-button"));
    expect(
      screen.getByText(
        "5 documents will be permanently deleted. This cannot be undone.",
      ),
    ).toBeDefined();
  });

  it("computes the remaining retention from the configured window", () => {
    // Trashed 10 days ago with a 7-day window: already past expiry.
    mocks.retentionDays = 7;
    mocks.documents = [makeTrashDocument()];
    render(<TrashView />, { wrapper: Wrapper });
    expect(screen.getByText(/Less than a day left/)).toBeDefined();
    expect(screen.queryByText(/20 days left/)).toBeNull();
  });

  it("falls back to the 30-day default when the config endpoint is unavailable", () => {
    mocks.retentionDays = undefined;
    mocks.documents = [makeTrashDocument()];
    render(<TrashView />, { wrapper: Wrapper });
    expect(screen.getByText(/20 days left/)).toBeDefined();
  });
});
