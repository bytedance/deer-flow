import { describe, expect, test } from "@rstest/core";

import { NAV_ITEMS } from "@/components/workspace/nav-registry";
import { enUS } from "@/core/i18n";
import { type NavGateContext } from "@/core/settings/nav-layout";

const userWithRuns = { permissions: ["runs:read"] };
const userWithoutRuns = { permissions: [] };

function ctx(overrides: Partial<NavGateContext> = {}): NavGateContext {
  return {
    user: null,
    staticMode: false,
    agentsEnabled: true,
    ...overrides,
  };
}

test("registry defines the shipped menu in order", () => {
  expect(NAV_ITEMS.map((item) => item.key)).toEqual([
    "new-chat",
    "chats",
    "search",
    "agents",
    "scheduled-tasks",
    "usage",
    "capabilities",
  ]);
});

test("new chat is pinned first, hidden from the menu group, and not configurable", () => {
  const newChat = NAV_ITEMS.find((item) => item.key === "new-chat");

  expect(newChat).toBeDefined();
  expect(newChat?.configurable).toBe(false);
  expect(newChat?.fixedPosition).toBe("first");
  expect(newChat?.showInMenu).toBe(false);
  expect(newChat?.label(enUS)).toBe("New chat");
  expect(newChat?.target).toEqual(
    expect.objectContaining({ kind: "link", href: "/workspace/chats/new" }),
  );
});

test("chats is a separate configurable entry", () => {
  const chats = NAV_ITEMS.find((item) => item.key === "chats");

  expect(chats).toBeDefined();
  expect(chats?.configurable).toBe(true);
  expect(chats?.fixedPosition).toBeUndefined();
  expect(chats?.showInMenu).not.toBe(false);
});

test("search and the page entries are configurable", () => {
  expect(
    NAV_ITEMS.filter((item) => item.configurable).map((item) => item.key),
  ).toEqual([
    "chats",
    "search",
    "agents",
    "scheduled-tasks",
    "usage",
    "capabilities",
  ]);
});

test("every item has a localized label, an icon and a target", () => {
  for (const item of NAV_ITEMS) {
    expect(item.label(enUS).length).toBeGreaterThan(0);
    expect(item.icon).toBeDefined();
    expect(item.target).toBeDefined();
  }
});

test("usage is enabled only with runs:read outside static mode", () => {
  const usage = NAV_ITEMS.find((item) => item.key === "usage");

  expect(usage).toBeDefined();
  expect(usage?.isEnabled?.(ctx())).toBe(false);
  expect(usage?.isEnabled?.(ctx({ user: userWithoutRuns }))).toBe(false);
  expect(usage?.isEnabled?.(ctx({ user: userWithRuns }))).toBe(true);
  expect(
    usage?.isEnabled?.(ctx({ user: userWithRuns, staticMode: true })),
  ).toBe(false);
});

test("agents is shown disabled while the api flag is off", () => {
  const agents = NAV_ITEMS.find((item) => item.key === "agents");

  expect(agents).toBeDefined();
  expect(agents?.isDisabled?.(ctx({ agentsEnabled: false }))).toBe(true);
  expect(agents?.isDisabled?.(ctx())).toBe(false);
});

describe("registry contract", () => {
  test("keys and orders are unique and non-empty", () => {
    const keys = NAV_ITEMS.map((item) => item.key);
    const orders = NAV_ITEMS.map((item) => item.order);

    expect(new Set(keys).size).toBe(keys.length);
    expect(new Set(orders).size).toBe(orders.length);
    for (const key of keys) {
      expect(key.trim().length).toBeGreaterThan(0);
    }
  });

  test("every entry can reach the menu", () => {
    // An entry that is neither configurable nor pinned is dropped by the
    // resolver, so the sidebar would silently lose it.
    for (const item of NAV_ITEMS) {
      expect(
        item.configurable || item.fixedPosition === "first",
        item.key,
      ).toBe(true);
    }
  });

  test("a pinned entry is never configurable", () => {
    for (const item of NAV_ITEMS.filter(
      (item) => item.fixedPosition !== undefined,
    )) {
      expect(item.configurable, item.key).toBe(false);
    }
  });

  test("only one entry is pinned first", () => {
    // Current product/implementation constraint, not an architectural
    // invariant: the dialog's pinned hint names New chat, and the dialog
    // assumes one locked entry above the sortable rows. Remove this test when
    // a second pinned entry is a real requirement and the hint has been
    // generalized.
    expect(
      NAV_ITEMS.filter((item) => item.fixedPosition === "first"),
    ).toHaveLength(1);
  });

  test("an entry rendered outside the menu is locked and pinned", () => {
    // Same category: `showInMenu: false` currently means "the header renders
    // it", and the resolver drops a core entry that is neither configurable
    // nor pinned. A future non-pinned header-only entry needs an explicit flag
    // before that holds.
    for (const item of NAV_ITEMS.filter((item) => item.showInMenu === false)) {
      expect(item.configurable, item.key).toBe(false);
      expect(item.fixedPosition, item.key).toBe("first");
    }
  });

  test("link targets are absolute and match their own href", () => {
    for (const item of NAV_ITEMS) {
      if (item.target.kind !== "link") continue;
      expect(item.target.href.startsWith("/"), item.key).toBe(true);
      expect(item.target.matches(item.target.href), item.key).toBe(true);
    }
  });
});
