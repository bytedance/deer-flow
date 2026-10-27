import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { SettingsDialog } from "@/components/workspace/settings/settings-dialog";
import {
  getSettingsDialogSnapshot,
  setSettingsDialogOpen,
} from "@/components/workspace/settings/settings-dialog-store";
import { WorkspaceHeader } from "@/components/workspace/workspace-header";
import { WorkspaceNavMenu } from "@/components/workspace/workspace-nav-menu";
import { WorkspaceSettingsDeepLink } from "@/components/workspace/workspace-settings-deep-link";
import { I18nProvider } from "@/core/i18n/context";

const navigation = rs.hoisted(() => ({
  searchParams: new URLSearchParams(),
  router: { replace: rs.fn() },
}));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/new",
  useRouter: () => navigation.router,
  useSearchParams: () => navigation.searchParams,
}));

rs.mock("next/dynamic", () => ({
  default: () => () => <div>Settings page</div>,
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

beforeEach(() => {
  document.cookie = "locale=en-US; path=/";
  navigation.searchParams = new URLSearchParams();
});

afterEach(() => {
  cleanup();
  setSettingsDialogOpen(false);
});

describe("enterprise workspace", () => {
  it("ignores old About deep links while keeping Appearance deep links", () => {
    navigation.searchParams = new URLSearchParams("settings=about");
    const { unmount } = render(<WorkspaceSettingsDeepLink />);
    expect(getSettingsDialogSnapshot().open).toBe(false);
    unmount();

    navigation.searchParams = new URLSearchParams("settings=appearance");
    render(<WorkspaceSettingsDeepLink />);
    expect(getSettingsDialogSnapshot()).toEqual({
      open: true,
      section: "appearance",
    });
  });

  it.each([true, false])("shows DDFW-Agent with sidebar open=%s", (open) => {
    render(
      <I18nProvider initialLocale="en-US">
        <SidebarProvider defaultOpen={open}>
          <WorkspaceHeader />
        </SidebarProvider>
      </I18nProvider>,
    );
    expect(screen.getByText("DDFW-Agent")).toBeDefined();
    expect(screen.queryByText("DeerFlow")).toBeNull();
    expect(screen.queryByText("DF")).toBeNull();
  });

  it("keeps Settings as the only menu action", async () => {
    render(
      <I18nProvider initialLocale="en-US">
        <SidebarProvider>
          <WorkspaceNavMenu />
        </SidebarProvider>
      </I18nProvider>,
    );
    fireEvent.pointerDown(screen.getByRole("button", { name: /Settings/ }), {
      button: 0,
      ctrlKey: false,
      pointerType: "mouse",
    });
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["Settings"]);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    fireEvent.click(items[0]!);
    expect(getSettingsDialogSnapshot()).toEqual({
      open: true,
      section: "appearance",
    });
  });

  it.each(["en-US", "zh-CN"] as const)(
    "keeps settings usable without an About section in %s",
    (locale) => {
      document.cookie = `locale=${locale}; path=/`;
      render(
        <I18nProvider initialLocale={locale}>
          <SettingsDialog open />
        </I18nProvider>,
      );
      const navigation = screen.getByRole("navigation");
      expect(navigation.textContent).not.toMatch(/About|关于/);
      expect(navigation.textContent).toMatch(/Appearance|外观/);
      expect(navigation.textContent).toMatch(/Tools|工具/);
    },
  );
});
