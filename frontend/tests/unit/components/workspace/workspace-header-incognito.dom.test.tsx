import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceHeader } from "@/components/workspace/workspace-header";
import { enUS } from "@/core/i18n/locales/en-US";

const mocks = rs.hoisted(() => ({
  incognitoEnabled: true,
  pathname: "/workspace/chats/new",
  search: "",
}));

rs.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => false }));
rs.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useSearchParams: () => new URLSearchParams(mocks.search),
}));
rs.mock("@/core/features/hooks", () => ({
  useIncognitoFeature: () => ({
    enabled: mocks.incognitoEnabled,
    idleTtlSeconds: 86400,
    isLoading: false,
  }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

function renderHeader() {
  return render(
    <SidebarProvider defaultOpen>
      <WorkspaceHeader />
    </SidebarProvider>,
  );
}

beforeEach(() => {
  mocks.incognitoEnabled = true;
  mocks.pathname = "/workspace/chats/new";
  mocks.search = "";
});

afterEach(cleanup);

describe("workspace header incognito entry", () => {
  test("offers the incognito entry when the server enables it", () => {
    renderHeader();

    const link = screen.getByRole("link", { name: enUS.incognito.entry });
    expect(link.getAttribute("href")).toBe(
      "/workspace/chats/new?incognito=true",
    );
    // Ordinary new chat still exists and is the active entry.
    expect(
      screen
        .getByRole("link", { name: enUS.sidebar.newChat })
        .getAttribute("data-active"),
    ).toBe("true");
    expect(link.getAttribute("data-active")).toBe("false");
  });

  test("keeps the incognito entry out when it is disabled", () => {
    mocks.incognitoEnabled = false;
    renderHeader();

    expect(
      screen.queryByRole("link", { name: enUS.incognito.entry }),
    ).toBeNull();
  });

  test("marks the incognito entry active on its own new-chat URL", () => {
    mocks.search = "incognito=true";
    renderHeader();

    expect(
      screen
        .getByRole("link", { name: enUS.incognito.entry })
        .getAttribute("data-active"),
    ).toBe("true");
    expect(
      screen
        .getByRole("link", { name: enUS.sidebar.newChat })
        .getAttribute("data-active"),
    ).toBe("false");
  });
});
