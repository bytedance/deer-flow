import type { User } from "@/core/auth/types";

export type NavGroup = "primary" | "more";

/**
 * The subset of an item the layout resolver needs. The rendered shape
 * (label / icon / target) lives in the workspace registry.
 */
export interface NavItemShape {
  key: string;
  configurable: boolean;
  /** Pinned items cannot be moved or hidden by the layout. */
  fixedPosition?: "first";
  defaultGroup: NavGroup;
  order: number;
  /** False hides the item entirely (e.g. Usage without runs:read). */
  isEnabled?: (ctx: NavGateContext) => boolean;
  /**
   * True keeps the item visible but inert (e.g. Agents while the API flag is
   * off). Disabled items still follow the saved layout, so the user can move
   * them before the feature is turned on.
   */
  isDisabled?: (ctx: NavGateContext) => boolean;
}

export interface NavGateContext {
  user: Pick<User, "permissions"> | null;
  staticMode: boolean;
  /**
   * The custom-agent API switch, the only switchable menu feature today.
   * A future switchable entry adds its own boolean here and in `nav-gate.ts`,
   * next to the hook that owns that feature's last-known cache.
   */
  agentsEnabled: boolean;
}

export interface NavLayout {
  version: 1;
  /** Configurable item keys shown directly in the sidebar, in order. */
  primary: string[];
  /** Configurable item keys collapsed under "More", in order. */
  more: string[];
}

/**
 * Fixed items (New chat) are not stored here; the resolver always pins them.
 * The rest follows the shipped product order, with Chats first.
 */
export const DEFAULT_NAV_LAYOUT: NavLayout = {
  version: 1,
  primary: [
    "chats",
    "search",
    "agents",
    "scheduled-tasks",
    "usage",
    "capabilities",
  ],
  more: [],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readKeys(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const seen = new Set<string>();
  const keys: string[] = [];
  for (const entry of value) {
    if (typeof entry !== "string" || entry.length === 0 || seen.has(entry)) {
      continue;
    }
    seen.add(entry);
    keys.push(entry);
  }
  return keys;
}

function cloneLayout(layout: NavLayout): NavLayout {
  return {
    version: 1,
    primary: [...layout.primary],
    more: [...layout.more],
  };
}

/** Fresh copy so callers can never mutate the shipped default. */
export function createDefaultNavLayout(): NavLayout {
  return cloneLayout(DEFAULT_NAV_LAYOUT);
}

/**
 * Tolerant reader for the stored layout: one malformed entry must not discard
 * the rest, and an unknown version falls back to the default menu.
 */
export function parseNavLayout(value: unknown): NavLayout {
  if (!isRecord(value) || value.version !== 1) {
    return cloneLayout(DEFAULT_NAV_LAYOUT);
  }
  const primary = readKeys(value.primary);
  const more = readKeys(value.more);
  if (primary === undefined || more === undefined) {
    return cloneLayout(DEFAULT_NAV_LAYOUT);
  }
  const placed = new Set(primary);
  return {
    version: 1,
    primary,
    more: more.filter((key) => !placed.has(key)),
  };
}

/**
 * Moves `key` within or across the two groups. `index` is applied after the
 * key is removed from its previous group, so callers can pass the target
 * item's index directly. Out-of-range indices append.
 */
export function moveNavItem(
  layout: NavLayout,
  key: string,
  target: NavGroup,
  index?: number,
): NavLayout {
  const primary = layout.primary.filter((entry) => entry !== key);
  const more = layout.more.filter((entry) => entry !== key);
  const list = target === "primary" ? primary : more;
  const at =
    index === undefined || index < 0 || index > list.length
      ? list.length
      : index;
  list.splice(at, 0, key);
  return { version: 1, primary, more };
}

function mergeGroup(
  savedKeys: string[],
  visibleKeys: string[],
  visible: Set<string>,
): string[] {
  const hidden = savedKeys.filter((key) => !visible.has(key));
  if (hidden.length === 0) return [...visibleKeys];

  const result = [...visibleKeys];
  const visibleNow = new Set(visibleKeys);
  const after = new Map<string, string[]>();
  const before = new Map<string, string[]>();
  const unanchored: string[] = [];

  for (const key of hidden) {
    const at = savedKeys.indexOf(key);
    let afterAnchor: string | undefined;
    let beforeAnchor: string | undefined;
    for (let i = at - 1; i >= 0; i -= 1) {
      const candidate = savedKeys[i];
      if (candidate === undefined) continue;
      if (visible.has(candidate) && visibleNow.has(candidate)) {
        afterAnchor = candidate;
        break;
      }
    }
    if (afterAnchor === undefined) {
      for (let i = at + 1; i < savedKeys.length; i += 1) {
        const candidate = savedKeys[i];
        if (candidate === undefined) continue;
        if (visible.has(candidate) && visibleNow.has(candidate)) {
          beforeAnchor = candidate;
          break;
        }
      }
    }
    if (afterAnchor !== undefined) {
      after.set(afterAnchor, [...(after.get(afterAnchor) ?? []), key]);
    } else if (beforeAnchor !== undefined) {
      before.set(beforeAnchor, [...(before.get(beforeAnchor) ?? []), key]);
    } else {
      unanchored.push(key);
    }
  }

  for (const [anchor, keys] of after) {
    const at = result.indexOf(anchor);
    if (at === -1) unanchored.push(...keys);
    else result.splice(at + 1, 0, ...keys);
  }
  for (const [anchor, keys] of before) {
    const at = result.indexOf(anchor);
    if (at === -1) unanchored.push(...keys);
    else result.splice(at, 0, ...keys);
  }
  result.push(...unanchored);
  return result;
}

/**
 * Saves the dialog's visible ordering without dropping entries the current
 * view cannot show (a gated entry such as Usage without `runs:read`) or does
 * not know (a key from another version). A hidden key keeps its position next
 * to the visible keys it followed or preceded in the saved layout, because a
 * saved layout outlives the entries that produced it.
 */
export function mergeNavLayout(
  saved: NavLayout,
  primary: string[],
  more: string[],
): NavLayout {
  const visible = new Set([...primary, ...more]);
  const mergedPrimary = mergeGroup(saved.primary, primary, visible);
  const mergedMore = mergeGroup(saved.more, more, visible).filter(
    (key) => !mergedPrimary.includes(key),
  );
  return { version: 1, primary: mergedPrimary, more: mergedMore };
}

export interface CommittedNavOrder {
  key: string;
  primary: string[];
  more: string[];
}

/**
 * The customization dialog renders a committed copy of the order so a drag can
 * show before the settings write lands. A saved layout that changes during the
 * drag must stay pending: marking it applied without showing it would let the
 * drop write the pre-drag order over the newer one. `holding` is true while a
 * drag is active; the caller runs this again once the drag ends.
 */
export function reconcileCommittedOrder(args: {
  committed: CommittedNavOrder;
  saved: CommittedNavOrder;
  holding: boolean;
}): { state: CommittedNavOrder; applied: boolean } {
  if (args.committed.key === args.saved.key || args.holding) {
    return { state: args.committed, applied: false };
  }
  return { state: args.saved, applied: true };
}

function orderByKeys<T extends NavItemShape>(items: T[], keys: string[]): T[] {
  const byKey = new Map(items.map((item) => [item.key, item]));
  const ordered: T[] = [];
  for (const key of keys) {
    const item = byKey.get(key);
    if (item) ordered.push(item);
  }
  return ordered;
}

/**
 * Places entries added after the layout was saved next to the entries whose
 * default order they follow, instead of at the bottom of a customized menu.
 * Listed entries keep the user's order.
 */
function insertByOrder<T extends NavItemShape>(
  listed: T[],
  unlisted: T[],
): T[] {
  const result = [...listed];
  for (const item of [...unlisted].sort((a, b) => a.order - b.order)) {
    const at = result.findIndex((entry) => entry.order > item.order);
    if (at === -1) result.push(item);
    else result.splice(at, 0, item);
  }
  return result;
}

/**
 * Applies the user's layout to the registry. Unknown keys are ignored, fixed
 * items stay pinned, disabled items remain visible and follow the layout, and
 * entries new since the layout was saved are inserted at the position their
 * default order implies.
 */
export function resolveNavLayout<T extends NavItemShape>(
  items: readonly T[],
  layout: NavLayout,
  ctx: NavGateContext,
): { primary: T[]; more: T[] } {
  const enabled = items.filter((item) => item.isEnabled?.(ctx) ?? true);
  const fixed = enabled.filter((item) => item.fixedPosition === "first");
  const configurable = enabled.filter(
    (item) => item.configurable && item.fixedPosition === undefined,
  );

  const listed = new Set([...layout.primary, ...layout.more]);
  const unlisted = configurable.filter((item) => !listed.has(item.key));

  const primary = [
    ...fixed,
    ...insertByOrder(
      orderByKeys(configurable, layout.primary),
      unlisted.filter((item) => item.defaultGroup === "primary"),
    ),
  ];
  const more = insertByOrder(
    orderByKeys(configurable, layout.more),
    unlisted.filter((item) => item.defaultGroup === "more"),
  );

  return { primary, more };
}
