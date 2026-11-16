import { expect, test } from "@rstest/core";

import {
  DEFAULT_NAV_LAYOUT,
  mergeNavLayout,
  moveNavItem,
  parseNavLayout,
  resolveNavLayout,
  type NavGateContext,
  type NavItemShape,
} from "@/core/settings/nav-layout";

const ctx: NavGateContext = {
  user: null,
  staticMode: false,
  agentsEnabled: true,
};

const items: NavItemShape[] = [
  {
    key: "new-chat",
    configurable: false,
    fixedPosition: "first",
    defaultGroup: "primary",
    order: -10,
  },
  {
    key: "chats",
    configurable: true,
    defaultGroup: "primary",
    order: 0,
  },
  {
    key: "search",
    configurable: true,
    defaultGroup: "primary",
    order: 10,
  },
  {
    key: "agents",
    configurable: true,
    defaultGroup: "primary",
    order: 20,
  },
  {
    key: "scheduled-tasks",
    configurable: true,
    defaultGroup: "primary",
    order: 30,
  },
  {
    key: "usage",
    configurable: true,
    defaultGroup: "primary",
    order: 40,
  },
  {
    key: "capabilities",
    configurable: true,
    defaultGroup: "primary",
    order: 50,
  },
];

function keys(list: NavItemShape[]): string[] {
  return list.map((item) => item.key);
}

test("the default layout pins new chat first and keeps the shipped product order", () => {
  const { primary, more } = resolveNavLayout(items, DEFAULT_NAV_LAYOUT, ctx);

  expect(keys(primary)).toEqual([
    "new-chat",
    "chats",
    "search",
    "agents",
    "scheduled-tasks",
    "usage",
    "capabilities",
  ]);
  expect(more).toEqual([]);
});

test("moving an item into more removes it from the primary group", () => {
  const layout = {
    version: 1 as const,
    primary: ["chats", "search", "agents", "scheduled-tasks", "capabilities"],
    more: ["usage"],
  };

  const { primary, more } = resolveNavLayout(items, layout, ctx);

  expect(keys(primary)).toEqual([
    "new-chat",
    "chats",
    "search",
    "agents",
    "scheduled-tasks",
    "capabilities",
  ]);
  expect(keys(more)).toEqual(["usage"]);
});

test("unknown keys are ignored instead of breaking the layout", () => {
  const layout = {
    version: 1 as const,
    primary: ["search", "ghost"],
    more: ["also-ghost"],
  };

  const { primary, more } = resolveNavLayout(items, layout, ctx);

  expect(keys(primary)).toEqual([
    "new-chat",
    "chats",
    "search",
    "agents",
    "scheduled-tasks",
    "usage",
    "capabilities",
  ]);
  expect(more).toEqual([]);
});

test("items missing from the layout are inserted at their default order", () => {
  const layout = { version: 1 as const, primary: ["search"], more: [] };

  const { primary } = resolveNavLayout(items, layout, ctx);

  expect(keys(primary)).toEqual([
    "new-chat",
    "chats",
    "search",
    "agents",
    "scheduled-tasks",
    "usage",
    "capabilities",
  ]);
});

test("a fixed item stays first even when the layout lists it elsewhere", () => {
  const layout = {
    version: 1 as const,
    primary: ["search"],
    more: ["new-chat"],
  };

  const { primary, more } = resolveNavLayout(items, layout, ctx);

  expect(keys(primary)[0]).toBe("new-chat");
  expect(keys(primary)).toHaveLength(7);
  expect(keys(more)).not.toContain("new-chat");
});

test("gated items are filtered out of both groups", () => {
  const gated = items.map((item) =>
    item.key === "usage" ? { ...item, isEnabled: () => false } : item,
  );

  const { primary, more } = resolveNavLayout(
    gated,
    { version: 1, primary: ["search"], more: ["usage"] },
    ctx,
  );

  expect(keys(primary)).not.toContain("usage");
  expect(keys(more)).not.toContain("usage");
});

test("a disabled item stays visible and follows the saved layout", () => {
  const gated = items.map((item) =>
    item.key === "agents" ? { ...item, isDisabled: () => true } : item,
  );

  const { primary, more } = resolveNavLayout(
    gated,
    { version: 1, primary: ["search"], more: ["agents"] },
    ctx,
  );

  expect(keys(primary)).toEqual([
    "new-chat",
    "chats",
    "search",
    "scheduled-tasks",
    "usage",
    "capabilities",
  ]);
  expect(keys(more)).toEqual(["agents"]);
});

test("mergeNavLayout keeps a hidden entry next to its visible neighbor", () => {
  const saved = {
    version: 1 as const,
    primary: ["chats", "usage", "search"],
    more: [],
  };

  // Usage is hidden for this viewer; reordering the visible entries must not
  // drop its saved position.
  expect(mergeNavLayout(saved, ["search", "chats"], [])).toEqual({
    version: 1,
    primary: ["search", "chats", "usage"],
    more: [],
  });
});

test("mergeNavLayout keeps a leading hidden entry beside its following neighbor", () => {
  const saved = {
    version: 1 as const,
    primary: ["usage", "chats", "search"],
    more: [],
  };

  expect(mergeNavLayout(saved, ["search", "chats"], [])).toEqual({
    version: 1,
    primary: ["search", "usage", "chats"],
    more: [],
  });
});

test("mergeNavLayout keeps unknown keys from another version", () => {
  const saved = {
    version: 1 as const,
    primary: ["chats", "ghost", "search"],
    more: [],
  };

  expect(mergeNavLayout(saved, ["search", "chats"], [])).toEqual({
    version: 1,
    primary: ["search", "chats", "ghost"],
    more: [],
  });
});

test("mergeNavLayout appends a hidden entry with no visible neighbor", () => {
  const saved = {
    version: 1 as const,
    primary: ["ghost", "also-ghost"],
    more: [],
  };

  expect(mergeNavLayout(saved, ["search"], [])).toEqual({
    version: 1,
    primary: ["search", "ghost", "also-ghost"],
    more: [],
  });
});

test("mergeNavLayout keeps hidden entries in both groups", () => {
  const saved = {
    version: 1 as const,
    primary: ["chats"],
    more: ["usage", "capabilities"],
  };

  expect(mergeNavLayout(saved, ["chats"], ["capabilities"])).toEqual({
    version: 1,
    primary: ["chats"],
    more: ["usage", "capabilities"],
  });
});

test("mergeNavLayout does not duplicate an entry moved to the other group", () => {
  const saved = {
    version: 1 as const,
    primary: ["chats", "usage"],
    more: [],
  };

  expect(mergeNavLayout(saved, ["chats"], ["usage"])).toEqual({
    version: 1,
    primary: ["chats"],
    more: ["usage"],
  });
});

test("mergeNavLayout keeps the dialog order when nothing is hidden", () => {
  const saved = {
    version: 1 as const,
    primary: ["chats", "search"],
    more: [],
  };

  expect(mergeNavLayout(saved, ["search", "chats"], [])).toEqual({
    version: 1,
    primary: ["search", "chats"],
    more: [],
  });
});

test("parseNavLayout falls back to the default for malformed values", () => {
  expect(parseNavLayout(null)).toEqual(DEFAULT_NAV_LAYOUT);
  expect(parseNavLayout({ version: 2, primary: ["search"], more: [] })).toEqual(
    DEFAULT_NAV_LAYOUT,
  );
  expect(parseNavLayout({ version: 1, primary: "nope", more: [] })).toEqual(
    DEFAULT_NAV_LAYOUT,
  );
});

test("parseNavLayout keeps valid entries and drops invalid ones item by item", () => {
  expect(
    parseNavLayout({
      version: 1,
      primary: ["search", 42, "search", null, "usage"],
      more: ["capabilities", {}, "capabilities"],
    }),
  ).toEqual({
    version: 1,
    primary: ["search", "usage"],
    more: ["capabilities"],
  });
});

test("parseNavLayout returns a copy so callers cannot mutate the default", () => {
  const parsed = parseNavLayout(DEFAULT_NAV_LAYOUT);
  parsed.primary.push("mutated");

  expect(DEFAULT_NAV_LAYOUT.primary).not.toContain("mutated");
});

test("parseNavLayout keeps a key in the first group that lists it", () => {
  expect(
    parseNavLayout({
      version: 1,
      primary: ["search"],
      more: ["search", "usage"],
    }),
  ).toEqual({ version: 1, primary: ["search"], more: ["usage"] });
});

test("moveNavItem moves an entry to the end of the other group", () => {
  const layout = {
    version: 1 as const,
    primary: ["search", "usage"],
    more: [],
  };

  expect(moveNavItem(layout, "usage", "more")).toEqual({
    version: 1,
    primary: ["search"],
    more: ["usage"],
  });
});

test("moveNavItem moves an entry back at the requested index", () => {
  const layout = {
    version: 1 as const,
    primary: ["search", "agents"],
    more: ["usage", "capabilities"],
  };

  expect(moveNavItem(layout, "capabilities", "primary", 1)).toEqual({
    version: 1,
    primary: ["search", "capabilities", "agents"],
    more: ["usage"],
  });
});

test("moveNavItem reorders within one group", () => {
  const layout = {
    version: 1 as const,
    primary: ["search", "agents", "usage"],
    more: [],
  };

  expect(moveNavItem(layout, "usage", "primary", 0)).toEqual({
    version: 1,
    primary: ["usage", "search", "agents"],
    more: [],
  });
});

test("moveNavItem clamps an out-of-range index and appends unknown keys", () => {
  const layout = { version: 1 as const, primary: ["search"], more: [] };

  expect(moveNavItem(layout, "search", "primary", 99)).toEqual({
    version: 1,
    primary: ["search"],
    more: [],
  });
  expect(moveNavItem(layout, "capabilities", "primary", -1)).toEqual({
    version: 1,
    primary: ["search", "capabilities"],
    more: [],
  });
});

test("moveNavItem never mutates the input layout", () => {
  const layout = { version: 1 as const, primary: ["search"], more: [] };
  moveNavItem(layout, "search", "more");

  expect(layout).toEqual({ version: 1, primary: ["search"], more: [] });
});
