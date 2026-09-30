import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { PropsWithChildren, ReactNode } from "react";

// Hoisted hook doubles: the page reads everything through the projects
// barrel, so the mock swaps data stores instead of the network.
const mocks = rs.hoisted(() => ({
  project: undefined as
    | {
        id: string;
        name: string;
        instructions: string;
        presentation: Record<string, unknown>;
        status: "active" | "archived";
        created_at: string;
        updated_at: string;
      }
    | undefined,
  projectsConfig: undefined as
    | { instructions_max_bytes: number; trash_retention_days: number }
    | undefined,
  patchMutate: rs.fn(),
  patchPending: false,
  patchSuccess: false,
}));

rs.mock("next/navigation", () => ({
  useParams: () => ({ id: "proj-1" }),
  usePathname: () => "/workspace/projects/proj-1",
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
}));

rs.mock("next/link", () => {
  const MockLink = ({
    href,
    children,
  }: {
    href: string;
    children: ReactNode;
  }) => <a href={href}>{children}</a>;
  return { default: MockLink };
});

rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => false,
}));

rs.mock("@/core/projects", () => ({
  PROJECTS_CONFIG_DEFAULT: {
    instructions_max_bytes: 8192,
    trash_retention_days: 30,
  },
  useProject: () => ({ data: mocks.project, isError: false }),
  useInfiniteProjectThreads: () => ({
    data: { pages: [[]] },
    isLoading: false,
    isError: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: rs.fn(),
  }),
  useProjectsConfig: () => ({ data: mocks.projectsConfig }),
  usePatchProject: () => ({
    mutate: mocks.patchMutate,
    isPending: mocks.patchPending,
    isSuccess: mocks.patchSuccess,
  }),
  useArchiveProject: () => ({ mutate: rs.fn(), isPending: false }),
  useRestoreProject: () => ({ mutate: rs.fn(), isPending: false }),
  useDeleteProject: () => ({ mutate: rs.fn(), isPending: false }),
}));

// Chrome around the section under test: layout shell and sibling tabs.
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: PropsWithChildren) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => <div />,
  WorkspaceBody: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));
rs.mock("@/components/workspace/projects/project-documents-section", () => ({
  ProjectDocumentsSection: () => <div />,
}));
rs.mock("@/components/workspace/projects/project-threads-section", () => ({
  ProjectThreadsSection: () => <div />,
}));

import ProjectPage from "@/app/workspace/projects/[id]/page";
import { I18nProvider } from "@/core/i18n/context";

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

function makeProject(instructions: string) {
  return {
    id: "proj-1",
    name: "Alpha",
    instructions,
    presentation: {},
    status: "active" as const,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };
}

function openInstructionsTab() {
  render(<ProjectPage />, { wrapper: Wrapper });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Instructions" }));
}

beforeEach(() => {
  mocks.project = makeProject("");
  mocks.projectsConfig = undefined;
  mocks.patchPending = false;
  mocks.patchSuccess = false;
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("ProjectPage instructions limit", () => {
  it("uses the server-configured byte cap for the counter and the over-cap guard", async () => {
    mocks.projectsConfig = {
      instructions_max_bytes: 100,
      trash_retention_days: 30,
    };
    mocks.project = makeProject("x".repeat(101));
    openInstructionsTab();
    expect(screen.getByText("101 / 100 bytes")).toBeDefined();
    // Over the configured cap: the guard fires and the save is blocked,
    // even though 101 bytes is far below the 8192-byte default.
    expect(screen.getByText(/over the 100-byte limit/)).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Save" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("keeps longer-than-default instructions editable when the server allows them", () => {
    mocks.projectsConfig = {
      instructions_max_bytes: 16384,
      trash_retention_days: 30,
    };
    mocks.project = makeProject("x".repeat(9000));
    openInstructionsTab();
    expect(screen.getByText("9000 / 16384 bytes")).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen
        .getByRole("textbox", { name: "Instructions" })
        .getAttribute("aria-invalid"),
    ).toBe("false");
  });

  it("falls back to the 8192-byte default when the config endpoint is unavailable", () => {
    mocks.projectsConfig = undefined;
    mocks.project = makeProject("x".repeat(42));
    openInstructionsTab();
    expect(screen.getByText("42 / 8192 bytes")).toBeDefined();
  });
});

describe("ProjectPage instructions reconciliation", () => {
  function renderInstructions() {
    const utils = render(<ProjectPage />, { wrapper: Wrapper });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Instructions" }));
    return utils;
  }

  function editor() {
    return screen.getByRole("textbox", { name: "Instructions" });
  }

  function refetchWith(instructions: string) {
    // A completed save round-trip (or any refetch) delivers a new project
    // snapshot; ``updated_at`` advances exactly like the gateway's row.
    mocks.project = {
      ...makeProject(instructions),
      updated_at: "2026-09-01T01:00:00Z",
    };
  }

  it("keeps keystrokes typed while a save is in flight when the refetch lands", () => {
    mocks.project = makeProject("base");
    const { rerender } = renderInstructions();
    fireEvent.change(editor(), { target: { value: "base v1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mocks.patchMutate).toHaveBeenCalledWith(
      { projectId: "proj-1", input: { instructions: "base v1" } },
      expect.objectContaining({ onError: expect.any(Function) }),
    );

    // Save still pending; the user keeps typing.
    mocks.patchPending = true;
    fireEvent.change(editor(), { target: { value: "base v1 v2" } });

    // The round-trip completes: the refetched row carries "base v1".
    mocks.patchPending = false;
    mocks.patchSuccess = true;
    refetchWith("base v1");
    rerender(<ProjectPage />);

    // The newer keystrokes survive — the section is no longer remounted on
    // updated_at and the diverged draft wins over the refetched value.
    expect(editor()).toHaveProperty("value", "base v1 v2");
  });

  it("syncs the refetched value into the editor when the user has not typed since saving", () => {
    mocks.project = makeProject("base");
    const { rerender } = renderInstructions();
    fireEvent.change(editor(), { target: { value: "base v1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    mocks.patchSuccess = true;
    refetchWith("base v1");
    rerender(<ProjectPage />);

    expect(editor()).toHaveProperty("value", "base v1");
    // Draft equals the server value: clean state + the saved indicator.
    expect(screen.getByRole("status")).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Save" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("submits the full merged draft on a second save after divergence", () => {
    mocks.project = makeProject("base");
    const { rerender } = renderInstructions();
    fireEvent.change(editor(), { target: { value: "base v1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.change(editor(), { target: { value: "base v1 v2" } });
    refetchWith("base v1");
    rerender(<ProjectPage />);

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mocks.patchMutate).toHaveBeenLastCalledWith(
      { projectId: "proj-1", input: { instructions: "base v1 v2" } },
      expect.objectContaining({ onError: expect.any(Function) }),
    );
  });

  it("reconciles an external instructions change while the editor is idle", () => {
    mocks.project = makeProject("base");
    const { rerender } = renderInstructions();
    expect(editor()).toHaveProperty("value", "base");

    refetchWith("external edit");
    rerender(<ProjectPage />);

    expect(editor()).toHaveProperty("value", "external edit");
  });
});

describe("ProjectPage rename reconciliation", () => {
  function renderSettings() {
    const utils = render(<ProjectPage />, { wrapper: Wrapper });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Settings" }));
    return utils;
  }

  function nameInput() {
    return screen.getByRole("textbox", { name: "Project name" });
  }

  function refetchWith(name: string, status: "active" | "archived" = "active") {
    // Any round-trip (rename save, archive/restore) advances updated_at.
    mocks.project = {
      ...makeProject(""),
      name,
      status,
      updated_at: "2026-09-01T01:00:00Z",
    };
  }

  it("keeps rename keystrokes typed while the save is in flight when the refetch lands", () => {
    mocks.project = makeProject("");
    const { rerender } = renderSettings();
    fireEvent.change(nameInput(), { target: { value: "Beta" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mocks.patchMutate).toHaveBeenCalledWith(
      { projectId: "proj-1", input: { name: "Beta" } },
      expect.objectContaining({ onError: expect.any(Function) }),
    );

    // Rename still pending; the user keeps typing.
    mocks.patchPending = true;
    fireEvent.change(nameInput(), { target: { value: "Beta v2" } });

    // The round-trip completes: the refetched row carries "Beta".
    mocks.patchPending = false;
    mocks.patchSuccess = true;
    refetchWith("Beta");
    rerender(<ProjectPage />);

    expect(nameInput()).toHaveProperty("value", "Beta v2");
  });

  it("syncs the refetched name into an idle field after a rename save", () => {
    mocks.project = makeProject("");
    const { rerender } = renderSettings();
    fireEvent.change(nameInput(), { target: { value: "Beta" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    mocks.patchSuccess = true;
    refetchWith("Beta");
    rerender(<ProjectPage />);

    expect(nameInput()).toHaveProperty("value", "Beta");
    expect(
      screen.getByRole("button", { name: "Save" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("does not clobber an unsaved rename draft on an archive round-trip", () => {
    mocks.project = makeProject("");
    const { rerender } = renderSettings();
    fireEvent.change(nameInput(), { target: { value: "Beta" } });

    // Archive flips the status and bumps updated_at; the name is unchanged.
    refetchWith("Alpha", "archived");
    rerender(<ProjectPage />);

    expect(nameInput()).toHaveProperty("value", "Beta");
  });

  it("keeps an idle-synced field stable across an archive round-trip", () => {
    mocks.project = makeProject("");
    const { rerender } = renderSettings();
    expect(nameInput()).toHaveProperty("value", "Alpha");

    refetchWith("Alpha", "archived");
    rerender(<ProjectPage />);

    expect(nameInput()).toHaveProperty("value", "Alpha");
    expect(screen.getByRole("button", { name: "Restore" })).toBeDefined();
  });
});
