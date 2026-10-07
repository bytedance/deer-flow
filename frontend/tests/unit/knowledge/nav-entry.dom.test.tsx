/**
 * Sidebar first-level entry for the knowledge page (spec §5.2 信息架构:
 * 知识库 entry sits next to 对话/智能体/定时任务 and links to
 * /workspace/knowledge).
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/knowledge",
}));

rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => ({ enabled: true }),
}));

rs.mock("@/core/features", () => ({
  useKnowledgeBaseEnabled: () => ({ enabled: true, scopeSelectionEnabled: false, isLoading: false }),
}));

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceNavChatList } from "@/components/workspace/workspace-nav-chat-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

function renderNav() {
  return render(
    <I18nContext.Provider value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}>
      <SidebarProvider>
        <WorkspaceNavChatList />
      </SidebarProvider>
    </I18nContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("workspace nav knowledge entry", () => {
  it("renders a first-level entry linking to /workspace/knowledge", () => {
    renderNav();

    const link = screen.getByRole("link", { name: enUS.sidebar.knowledge });
    expect(link.getAttribute("href")).toBe("/workspace/knowledge");
  });

  it("marks the entry active on knowledge routes", () => {
    renderNav();

    const link = screen.getByRole("link", { name: enUS.sidebar.knowledge });
    expect(link.closest("[data-active]")?.getAttribute("data-active")).toBe("true");
  });
});
