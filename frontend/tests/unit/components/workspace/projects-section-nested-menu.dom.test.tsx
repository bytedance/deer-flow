import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { ProjectsSection } from "@/components/workspace/projects-section";
import { ThreadDeleteDialogProvider } from "@/components/workspace/thread-delete-dialog";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { PROJECTS_QUERY_KEY, type Project } from "@/core/projects";
import { updateLocalSettings } from "@/core/settings/store";
import { INFINITE_THREADS_QUERY_KEY_PREFIX } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";
import { THREAD_PROJECT_METADATA_KEY } from "@/core/threads/utils";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

const ACTIVE_PROJECT_ID = "project-active";
const ARCHIVED_PROJECT_ID = "project-archived";

function makeProject(
  id: string,
  name: string,
  status: Project["status"],
): Project {
  return {
    id,
    name,
    instructions: "",
    presentation: {},
    status,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}

function makeThread(id: string, projectId: string): AgentThread {
  return {
    thread_id: id,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    status: "idle",
    metadata: { [THREAD_PROJECT_METADATA_KEY]: projectId },
    values: { title: `Chat in ${projectId}` },
  } as unknown as AgentThread;
}

const user = {
  id: "user-1",
  email: "user@example.test",
  system_role: "user",
} as User;

/**
 * Seed every query `ProjectsSection` reads in grouped mode so the section
 * renders from cache without touching the network: both project lists and
 * the non-archived infinite thread search that the groups partition.
 */
function renderGroupedSection(): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  queryClient.setQueryData(
    [...PROJECTS_QUERY_KEY, { status: "active" }],
    [makeProject(ACTIVE_PROJECT_ID, "Active project", "active")],
  );
  queryClient.setQueryData(
    [...PROJECTS_QUERY_KEY, { status: "archived" }],
    [makeProject(ARCHIVED_PROJECT_ID, "Archived project", "archived")],
  );
  queryClient.setQueryData(
    [...INFINITE_THREADS_QUERY_KEY_PREFIX, { archived: false }],
    {
      pages: [
        [
          makeThread("thread-active", ACTIVE_PROJECT_ID),
          makeThread("thread-archived", ARCHIVED_PROJECT_ID),
        ],
      ],
      pageParams: [0],
    },
  );
  const tree: ReactNode = (
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider initialUser={user}>
          <SidebarProvider>
            <ThreadDeleteDialogProvider>
              <ProjectsSection />
            </ThreadDeleteDialogProvider>
          </SidebarProvider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
  return render(tree);
}

function menuOf(element: Element): HTMLElement | null {
  return element.closest<HTMLElement>('[data-sidebar="menu"]');
}

beforeEach(() => {
  updateLocalSettings("projectsDisplayMode", "grouped");
});

afterEach(() => {
  updateLocalSettings("projectsDisplayMode", "flat");
  rs.restoreAllMocks();
  cleanup();
});

describe("ProjectsSection grouped-mode nested menus", () => {
  // happy-dom has no layout engine, so the regression is pinned at the class
  // level: `SidebarMenu` defaults to `w-full`, and an indented (`ml-4`) menu
  // that keeps it is 16px wider than its container — the absolutely
  // positioned row kebab (`right-1`) then lands outside the sidebar and gets
  // clipped. Every indented menu must swap `w-full` for `w-auto`.
  it("indents thread rows without overflowing the sidebar width", async () => {
    const { container } = renderGroupedSection();

    // The Archived group starts collapsed; expand it so its doubly nested
    // menus (group → project → rows) mount and get checked too.
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    const kebabs = await screen.findAllByRole("button", { name: "More" });
    expect(kebabs).toHaveLength(2);

    for (const kebab of kebabs) {
      const menu = menuOf(kebab);
      expect(menu).not.toBeNull();
      expect(menu?.classList.contains("ml-4")).toBe(true);
      expect(menu?.classList.contains("w-auto")).toBe(true);
      expect(menu?.classList.contains("w-full")).toBe(false);
    }

    const menus = [
      ...container.querySelectorAll<HTMLElement>('[data-sidebar="menu"]'),
    ];
    const nestedMenus = menus.filter((menu) =>
      Boolean(menu.parentElement && menuOf(menu.parentElement)),
    );
    // Active project rows, the Archived group, and the archived project rows.
    expect(nestedMenus).toHaveLength(3);
    for (const menu of nestedMenus) {
      expect(menu.classList.contains("w-auto")).toBe(true);
      expect(menu.classList.contains("w-full")).toBe(false);
    }

    // The outermost menu is not indented and keeps the primitive's full width.
    const rootMenus = menus.filter((menu) => !nestedMenus.includes(menu));
    expect(rootMenus).toHaveLength(1);
    expect(rootMenus[0]?.classList.contains("w-full")).toBe(true);
  });
});
