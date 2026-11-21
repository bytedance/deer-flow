import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

const mocks = rs.hoisted(() => ({
  agentsEnabled: { value: true },
  user: { value: null as { permissions: string[] } | null },
  settings: {
    value: {
      navLayout: {
        version: 1 as const,
        primary: [
          "search",
          "agents",
          "scheduled-tasks",
          "usage",
          "capabilities",
        ],
        more: [] as string[],
      },
    },
  },
}));

rs.mock("next/dynamic", () => ({
  __esModule: true,
  default: () => () => null,
}));
rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats",
}));
rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
rs.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => false }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/components/workspace/nav-gate", () => ({
  useNavGateContext: () => ({
    user: mocks.user.value,
    staticMode: false,
    agentsEnabled: mocks.agentsEnabled.value,
  }),
}));
rs.mock("@/core/settings/hooks", () => ({
  useLocalSettings: () => [mocks.settings.value, rs.fn()],
}));

import { SidebarProvider, useSidebar } from "@/components/ui/sidebar";
import { WorkspaceNavChatList } from "@/components/workspace/workspace-nav-chat-list";
import { enUS } from "@/core/i18n/locales/en-US";
import { OPEN_SEARCH_EVENT } from "@/core/search/api";

const runsReader = { permissions: ["runs:read"] };

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
  mocks.agentsEnabled.value = true;
  mocks.user.value = null;
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["search", "agents", "scheduled-tasks", "usage", "capabilities"],
      more: [],
    },
  };
});

afterEach(() => {
  cleanup();
  rs.resetAllMocks();
});

test("renders chats first, then the registry order, then More", () => {
  renderNav();

  expect(menuLabels()).toEqual([
    enUS.sidebar.chats,
    enUS.workspaceSearch.open,
    enUS.sidebar.agents,
    enUS.sidebar.scheduledTasks,
    enUS.capabilities.title,
    enUS.sidebar.more,
  ]);
});

test("hides gated entries such as token usage without runs:read", () => {
  renderNav();

  expect(menuLabels()).not.toContain(enUS.usage.title);
});

test("shows token usage for a reader with runs:read", () => {
  mocks.user.value = runsReader;
  renderNav();

  expect(menuLabels()).toEqual([
    enUS.sidebar.chats,
    enUS.workspaceSearch.open,
    enUS.sidebar.agents,
    enUS.sidebar.scheduledTasks,
    enUS.usage.title,
    enUS.capabilities.title,
    enUS.sidebar.more,
  ]);
});

test("moves configured entries into the More menu", async () => {
  mocks.user.value = runsReader;
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["search", "agents", "scheduled-tasks", "capabilities"],
      more: ["usage"],
    },
  };
  renderNav();

  expect(menuLabels()).not.toContain(enUS.usage.title);

  fireEvent.keyDown(screen.getByRole("button", { name: enUS.sidebar.more }), {
    key: "Enter",
  });

  expect(
    await screen.findByRole("menuitem", { name: enUS.usage.title }),
  ).toBeTruthy();
  expect(
    screen.getByRole("menuitem", { name: enUS.sidebar.customize }),
  ).toBeTruthy();
});

test("opens search from the More menu when it is collapsed there", async () => {
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["agents", "scheduled-tasks", "capabilities"],
      more: ["search"],
    },
  };
  const onOpenSearch = rs.fn();
  window.addEventListener(OPEN_SEARCH_EVENT, onOpenSearch);
  renderNav();

  expect(menuLabels()).not.toContain(enUS.workspaceSearch.open);

  fireEvent.keyDown(screen.getByRole("button", { name: enUS.sidebar.more }), {
    key: "Enter",
  });

  fireEvent.click(
    await screen.findByRole("menuitem", {
      name: enUS.workspaceSearch.open,
    }),
  );
  expect(onOpenSearch).toHaveBeenCalledTimes(1);
  window.removeEventListener(OPEN_SEARCH_EVENT, onOpenSearch);
});

test("keeps a disabled agents entry visible with its reason", () => {
  mocks.agentsEnabled.value = false;
  renderNav();

  expect(menuLabels()).toContain(enUS.sidebar.agents);
  expect(screen.getByText(enUS.sidebar.featureDisabledTooltip)).toBeTruthy();
});

test("shows a disabled entry in the More menu as inert with its reason", async () => {
  mocks.agentsEnabled.value = false;
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["chats", "search", "scheduled-tasks", "capabilities"],
      more: ["agents"],
    },
  };
  renderNav();

  expect(menuLabels()).not.toContain(enUS.sidebar.agents);
  fireEvent.keyDown(screen.getByRole("button", { name: enUS.sidebar.more }), {
    key: "Enter",
  });

  const item = await screen.findByRole("menuitem", {
    name: enUS.sidebar.agents,
  });
  expect(item.getAttribute("aria-disabled")).toBe("true");
  expect(item.className).toContain("text-muted-foreground/50");
  expect(item.getAttribute("aria-describedby")).toBe(
    "agents-more-disabled-reason",
  );
  expect(screen.getByRole("tooltip").textContent).toBe(
    enUS.sidebar.featureDisabledTooltip,
  );
});

test("ignores unknown keys from an older or newer layout", () => {
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["ghost", "search"],
      more: ["also-ghost"],
    },
  };
  renderNav();

  expect(menuLabels()).toEqual([
    enUS.sidebar.chats,
    enUS.workspaceSearch.open,
    enUS.sidebar.agents,
    enUS.sidebar.scheduledTasks,
    enUS.capabilities.title,
    enUS.sidebar.more,
  ]);
});

function MobileProbe() {
  const { openMobile, setOpenMobile } = useSidebar();
  return (
    <>
      <button type="button" onClick={() => setOpenMobile(true)}>
        open mobile drawer
      </button>
      <output data-testid="mobile-open">{String(openMobile)}</output>
    </>
  );
}

function renderNavWithMobileProbe() {
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["search", "scheduled-tasks", "usage", "capabilities"],
      more: ["agents"],
    },
  };
  render(
    <SidebarProvider>
      <WorkspaceNavChatList />
      <MobileProbe />
    </SidebarProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "open mobile drawer" }));
  expect(screen.getByTestId("mobile-open").textContent).toBe("true");
}

async function openMoreAgentsLink() {
  fireEvent.keyDown(screen.getByRole("button", { name: enUS.sidebar.more }), {
    key: "Enter",
  });
  return screen.findByRole("menuitem", { name: enUS.sidebar.agents });
}

test("keeps the mobile drawer open for a modified click on a More link", async () => {
  renderNavWithMobileProbe();

  fireEvent.click(await openMoreAgentsLink(), { ctrlKey: true });

  expect(screen.getByTestId("mobile-open").textContent).toBe("true");
});

test("closes the mobile drawer for a plain click on a More link", async () => {
  renderNavWithMobileProbe();

  fireEvent.click(await openMoreAgentsLink());

  expect(screen.getByTestId("mobile-open").textContent).toBe("false");
});
