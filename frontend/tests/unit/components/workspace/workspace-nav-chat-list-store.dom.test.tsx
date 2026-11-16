import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { act, cleanup, render } from "@testing-library/react";

rs.mock("next/dynamic", () => ({
  __esModule: true,
  default: () => () => null,
}));
rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats",
}));
rs.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => false }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/components/workspace/nav-gate", () => ({
  useNavGateContext: () => ({
    user: null,
    staticMode: false,
    agentsEnabled: true,
  }),
}));

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceNavChatList } from "@/components/workspace/workspace-nav-chat-list";
import { enUS } from "@/core/i18n/locales/en-US";
import { updateLocalSettings } from "@/core/settings/store";

function renderNav() {
  return render(
    <SidebarProvider>
      <WorkspaceNavChatList />
    </SidebarProvider>,
  );
}

function menuLabels(): string[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>('[data-sidebar="menu-button"]'),
  ).map((element) => element.querySelector("span")?.textContent ?? "");
}

beforeEach(() => {
  updateLocalSettings("navLayout", {
    version: 1,
    primary: ["search", "agents", "scheduled-tasks", "usage", "capabilities"],
    more: [],
  });
});

afterEach(() => {
  cleanup();
});

test("re-renders the sidebar when the saved layout changes", () => {
  renderNav();

  expect(menuLabels()).toContain(enUS.capabilities.title);

  act(() => {
    updateLocalSettings("navLayout", {
      version: 1,
      primary: ["chats", "search", "agents", "scheduled-tasks"],
      more: ["capabilities"],
    });
  });

  expect(menuLabels()).not.toContain(enUS.capabilities.title);

  act(() => {
    updateLocalSettings("navLayout", {
      version: 1,
      primary: ["search", "agents", "scheduled-tasks", "usage", "capabilities"],
      more: [],
    });
  });

  expect(menuLabels()).toContain(enUS.capabilities.title);
});
