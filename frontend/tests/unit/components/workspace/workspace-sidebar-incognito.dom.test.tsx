import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  IncognitoModeProvider,
  usePublishIncognitoMode,
} from "@/components/workspace/incognito-mode-context";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";

rs.mock("@/components/ui/sidebar", () => ({
  SidebarHeader: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  SidebarContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  SidebarFooter: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  SidebarRail: () => null,
  useSidebar: () => ({ isMobile: false }),
}));
rs.mock("@/core/threads/activity", () => ({
  useThreadActivity: () => undefined,
}));
rs.mock("@/components/workspace/workspace-sidebar-frame", () => ({
  WorkspaceSidebarFrame: ({ children }: { children: ReactNode }) => (
    <div data-testid="workspace-sidebar">{children}</div>
  ),
  useWorkspaceSidebarExpanded: () => true,
}));
rs.mock("@/components/workspace/workspace-header", () => ({
  WorkspaceHeader: () => null,
}));
rs.mock("@/components/workspace/workspace-nav-chat-list", () => ({
  WorkspaceNavChatList: () => null,
}));
rs.mock("@/components/workspace/workspace-nav-menu", () => ({
  WorkspaceNavMenu: () => null,
}));
rs.mock("@/components/workspace/channels/workspace-channels-list", () => ({
  WorkspaceChannelsList: () => null,
}));
rs.mock("@/components/workspace/plugin-navigation", () => ({
  PluginNavigation: () => null,
}));
rs.mock("@/components/workspace/projects-section", () => ({
  ProjectsSection: () => null,
}));
rs.mock("@/components/workspace/recent-chat-list", () => ({
  RecentChatList: () => null,
}));
rs.mock("@/components/workspace/thread-delete-dialog", () => ({
  ThreadDeleteDialogProvider: ({ children }: { children: ReactNode }) => (
    <>{children}</>
  ),
}));

function Publisher({ active }: { active: boolean }) {
  usePublishIncognitoMode(active);
  return null;
}

function renderSidebar(active: boolean) {
  return render(
    <IncognitoModeProvider>
      <Publisher active={active} />
      <WorkspaceSidebar />
    </IncognitoModeProvider>,
  );
}

afterEach(cleanup);

describe("workspace sidebar in an incognito chat", () => {
  test("is unmounted, not collapsed", () => {
    renderSidebar(true);

    expect(screen.queryByTestId("workspace-sidebar")).toBeNull();
  });

  test("stays mounted in an ordinary chat", () => {
    renderSidebar(false);

    expect(screen.getByTestId("workspace-sidebar")).not.toBeNull();
  });
});
