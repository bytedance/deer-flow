import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  agentsEnabled: { value: true },
  user: { value: null as { permissions: string[] } | null },
  setSettings: rs.fn(),
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

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats",
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
  useLocalSettings: () => [mocks.settings.value, mocks.setSettings],
}));

import { NavCustomizeDialog } from "@/components/workspace/nav-customize-dialog";
import { enUS } from "@/core/i18n/locales/en-US";

const runsReader = { permissions: ["runs:read"] };

function renderDialog() {
  return render(<NavCustomizeDialog open onOpenChange={() => undefined} />);
}

function group(name: "primary" | "more"): HTMLElement {
  const element = document.querySelector<HTMLElement>(`[data-group="${name}"]`);
  if (!element) throw new Error(`missing ${name} group`);
  return element;
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

test("shows the menu and More groups with new chat locked first", () => {
  renderDialog();

  expect(within(group("primary")).getByText(enUS.sidebar.newChat)).toBeTruthy();
  expect(
    within(group("primary")).getByText(enUS.sidebar.pinnedHint),
  ).toBeTruthy();
  expect(within(group("primary")).getByText(enUS.sidebar.chats)).toBeTruthy();
  expect(
    within(group("more")).getByText(enUS.sidebar.emptyMoreGroup),
  ).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeTruthy();
});

test("only lists entries the current user can see", () => {
  renderDialog();

  expect(within(group("primary")).queryByText(enUS.usage.title)).toBeNull();
  expect(
    screen.queryByRole("button", {
      name: enUS.sidebar.moveToMore(enUS.usage.title),
    }),
  ).toBeNull();
});

test("moves an entry into More and persists the layout", () => {
  mocks.user.value = runsReader;
  renderDialog();

  fireEvent.click(
    screen.getByRole("button", {
      name: enUS.sidebar.moveToMore(enUS.usage.title),
    }),
  );

  expect(mocks.setSettings).toHaveBeenCalledWith("navLayout", {
    version: 1,
    primary: ["chats", "search", "agents", "scheduled-tasks", "capabilities"],
    more: ["usage"],
  });
  expect(within(group("more")).getByText(enUS.usage.title)).toBeTruthy();
  expect(within(group("primary")).queryByText(enUS.usage.title)).toBeNull();
});

test("moves an entry back to the menu at the end and persists", () => {
  mocks.user.value = runsReader;
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["search", "agents", "scheduled-tasks", "capabilities"],
      more: ["usage"],
    },
  };
  renderDialog();

  fireEvent.click(
    screen.getByRole("button", {
      name: enUS.sidebar.moveToMenu(enUS.usage.title),
    }),
  );

  expect(mocks.setSettings).toHaveBeenCalledWith("navLayout", {
    version: 1,
    primary: [
      "chats",
      "search",
      "agents",
      "scheduled-tasks",
      "capabilities",
      "usage",
    ],
    more: [],
  });
  expect(within(group("primary")).getByText(enUS.usage.title)).toBeTruthy();
});

test("renders entries already stored in More under that group", () => {
  mocks.user.value = runsReader;
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["agents", "scheduled-tasks", "capabilities"],
      more: ["search", "usage"],
    },
  };
  renderDialog();

  expect(
    within(group("more")).getByText(enUS.workspaceSearch.open),
  ).toBeTruthy();
  expect(within(group("more")).getByText(enUS.usage.title)).toBeTruthy();
  expect(
    within(group("primary")).queryByText(enUS.workspaceSearch.open),
  ).toBeNull();
});

test("keeps a disabled entry visible and movable", () => {
  mocks.agentsEnabled.value = false;
  renderDialog();

  expect(within(group("primary")).getByText(enUS.sidebar.agents)).toBeTruthy();
  expect(
    screen.getByRole("button", {
      name: enUS.sidebar.dragToReorder(enUS.sidebar.agents),
    }),
  ).toBeTruthy();

  fireEvent.click(
    screen.getByRole("button", {
      name: enUS.sidebar.moveToMore(enUS.sidebar.agents),
    }),
  );

  expect(mocks.setSettings).toHaveBeenCalledWith("navLayout", {
    version: 1,
    primary: ["chats", "search", "scheduled-tasks", "usage", "capabilities"],
    more: ["agents"],
  });
  expect(within(group("more")).getByText(enUS.sidebar.agents)).toBeTruthy();
});

test("greys out a feature-disabled entry and explains it", () => {
  mocks.agentsEnabled.value = false;
  renderDialog();

  const label = within(group("primary")).getByText(enUS.sidebar.agents);
  expect(label.className).toContain("text-muted-foreground/50");
  expect(screen.getByText(enUS.sidebar.featureDisabledTooltip)).toBeTruthy();
  expect(
    screen.getByRole("button", {
      name: enUS.sidebar.dragToReorder(enUS.sidebar.agents),
    }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("button", {
        name: enUS.sidebar.dragToReorder(enUS.sidebar.agents),
      })
      .getAttribute("aria-describedby"),
  ).toBe("agents-dialog-disabled-reason");
  expect(
    screen
      .getByRole("button", {
        name: enUS.sidebar.moveToMore(enUS.sidebar.agents),
      })
      .getAttribute("aria-describedby"),
  ).toBe("agents-dialog-disabled-reason");
});

test("adds a gated entry when the gate resolves after the dialog opens", () => {
  const view = renderDialog();

  expect(within(group("primary")).queryByText(enUS.usage.title)).toBeNull();

  mocks.user.value = runsReader;
  view.rerender(<NavCustomizeDialog open onOpenChange={() => undefined} />);

  expect(within(group("primary")).getByText(enUS.usage.title)).toBeTruthy();
});

test("keeps a hidden entry in the saved layout when moving another row", () => {
  mocks.settings.value = {
    navLayout: {
      version: 1,
      primary: ["usage", "search", "agents", "scheduled-tasks", "capabilities"],
      more: [],
    },
  };
  renderDialog();

  fireEvent.click(
    screen.getByRole("button", {
      name: enUS.sidebar.moveToMore(enUS.sidebar.agents),
    }),
  );

  expect(mocks.setSettings).toHaveBeenCalledWith("navLayout", {
    version: 1,
    primary: ["chats", "usage", "search", "scheduled-tasks", "capabilities"],
    more: ["agents"],
  });
});
