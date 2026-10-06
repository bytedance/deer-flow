"use client";

/**
 * Local persistence for user-defined card drawers (2026-09-04): named,
 * icon+color-coded groups that partition the manual cards inside 我的条目.
 *
 * Mirrors `kb-order.ts` — localStorage by design: the grouping is small,
 * personal and cosmetic, while the backend keeps the cards themselves as the
 * cross-device source of truth. A device that never created drawers simply
 * shows the flat unfiled list.
 *
 * Membership is a PARTITION: each card lives in at most one drawer; a card with
 * no (or a stale) mapping is "unfiled" and listed first. Deleting a drawer only
 * drops its membership entries — the cards themselves are never touched.
 */
import { useCallback, useState } from "react";

export const DRAWER_ICON_KEYS = [
  "folder",
  "star",
  "layers",
  "briefcase",
  "target",
  "zap",
  "flag",
  "heart",
  "bookmark",
  "clock",
  "message",
  "grid",
] as const;
export type DrawerIconKey = (typeof DRAWER_ICON_KEYS)[number];

export const DRAWER_COLOR_KEYS = [
  "emerald",
  "teal",
  "sky",
  "blue",
  "indigo",
  "violet",
  "purple",
  "pink",
  "rose",
  "orange",
  "amber",
  "lime",
] as const;
export type DrawerColorKey = (typeof DRAWER_COLOR_KEYS)[number];

/**
 * Accent hex per color (Tailwind 500-level: readable as an icon/name on both
 * light and dark surfaces). The chip tint is derived as the accent at ~12%
 * alpha (`${accent}1F`), so a single value works in both themes — no per-mode
 * palette needed.
 */
export const DRAWER_COLORS: Record<DrawerColorKey, { accent: string }> = {
  emerald: { accent: "#10B981" },
  teal: { accent: "#14B8A6" },
  sky: { accent: "#0EA5E9" },
  blue: { accent: "#3B82F6" },
  indigo: { accent: "#6366F1" },
  violet: { accent: "#8B5CF6" },
  purple: { accent: "#A855F7" },
  pink: { accent: "#EC4899" },
  rose: { accent: "#F43F5E" },
  orange: { accent: "#F97316" },
  amber: { accent: "#F59E0B" },
  lime: { accent: "#84CC16" },
};

export const DRAWER_DEFAULT_ICON: DrawerIconKey = "folder";
export const DRAWER_DEFAULT_COLOR: DrawerColorKey = "emerald";

export interface CardDrawer {
  id: string;
  name: string;
  icon: DrawerIconKey;
  color: DrawerColorKey;
  /**
   * 收起（2026-09-04）：标签上的 × 把抽屉从标签行收起（不删除、membership
   * 保留），收进头部右侧 -> 下拉，可从那里点击重新显示。缺省/undefined = 显示。
   */
  hidden?: boolean;
}

export interface CardDrawerState {
  /** Drawer definitions, in user-chosen display order. */
  drawers: CardDrawer[];
  /** cardId -> drawerId. Absent (or pointing at a gone drawer) = unfiled. */
  membership: Record<string, string>;
}

const EMPTY_STATE: CardDrawerState = { drawers: [], membership: {} };

const ICON_KEY_SET = new Set<string>(DRAWER_ICON_KEYS);
const COLOR_KEY_SET = new Set<string>(DRAWER_COLOR_KEYS);

export function cardDrawersKey(kbId: string): string {
  return `deerflow.knowledge.card-drawers.${kbId}.v1`;
}

function newDrawerId(): string {
  try {
    if (
      typeof crypto !== "undefined" &&
      typeof crypto.randomUUID === "function"
    ) {
      return crypto.randomUUID();
    }
  } catch {
    // Fall through to the timestamp id.
  }
  return `drawer-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Parse + sanitize the stored payload; anything malformed degrades to empty. */
function sanitize(parsed: unknown): CardDrawerState {
  if (typeof parsed !== "object" || parsed === null) return EMPTY_STATE;
  const raw = parsed as { drawers?: unknown; membership?: unknown };

  const drawers: CardDrawer[] = Array.isArray(raw.drawers)
    ? raw.drawers.flatMap((item): CardDrawer[] => {
        if (typeof item !== "object" || item === null) return [];
        const d = item as Record<string, unknown>;
        if (typeof d.id !== "string" || typeof d.name !== "string") return [];
        const icon = ICON_KEY_SET.has(d.icon as string)
          ? (d.icon as DrawerIconKey)
          : DRAWER_DEFAULT_ICON;
        const color = COLOR_KEY_SET.has(d.color as string)
          ? (d.color as DrawerColorKey)
          : DRAWER_DEFAULT_COLOR;
        const hidden = d.hidden === true;
        return [
          {
            id: d.id,
            name: d.name,
            icon,
            color,
            // 仅收起时才写 hidden，保持无 hidden 抽屉的读写往返保真。
            ...(hidden ? { hidden: true } : {}),
          },
        ];
      })
    : [];

  const membership: Record<string, string> = {};
  if (typeof raw.membership === "object" && raw.membership !== null) {
    for (const [cardId, drawerId] of Object.entries(
      raw.membership as Record<string, unknown>,
    )) {
      if (typeof drawerId === "string") membership[cardId] = drawerId;
    }
  }

  return { drawers, membership };
}

export function readCardDrawers(kbId: string): CardDrawerState {
  try {
    const raw = window.localStorage.getItem(cardDrawersKey(kbId));
    if (!raw) return EMPTY_STATE;
    return sanitize(JSON.parse(raw));
  } catch {
    // Private mode / quota / garbage — grouping is a nicety, never a crash.
    return EMPTY_STATE;
  }
}

export function writeCardDrawers(kbId: string, state: CardDrawerState): void {
  try {
    window.localStorage.setItem(cardDrawersKey(kbId), JSON.stringify(state));
  } catch {
    // Best effort only; in-memory state still applies for this session.
  }
}

export interface CreateDrawerInput {
  name: string;
  icon: DrawerIconKey;
  color: DrawerColorKey;
}

export type DrawerPatch = Partial<Omit<CardDrawer, "id">>;

export function useCardDrawers(kbId: string): {
  drawers: CardDrawer[];
  membership: Record<string, string>;
  drawerOf: (cardId: string) => string | undefined;
  createDrawer: (input: CreateDrawerInput) => string;
  updateDrawer: (id: string, patch: DrawerPatch) => void;
  deleteDrawer: (id: string) => void;
  setDrawerHidden: (id: string, hidden: boolean) => void;
  revealDrawerToFront: (id: string) => void;
  moveCard: (cardId: string, drawerId: string | null) => void;
  moveCards: (cardIds: string[], drawerId: string | null) => void;
} {
  const [state, setState] = useState<CardDrawerState>(() =>
    readCardDrawers(kbId),
  );
  // Re-read when the library changes (the panel is kept alive across kb
  // switches) — render-time derived-state reset, no effect round-trip.
  const [loadedKb, setLoadedKb] = useState(kbId);
  if (loadedKb !== kbId) {
    setLoadedKb(kbId);
    setState(readCardDrawers(kbId));
  }

  const persist = useCallback(
    (next: CardDrawerState) => {
      setState(next);
      writeCardDrawers(kbId, next);
    },
    [kbId],
  );

  const drawerOf = useCallback(
    (cardId: string) => state.membership[cardId],
    [state.membership],
  );

  const createDrawer = useCallback(
    (input: CreateDrawerInput) => {
      const drawer: CardDrawer = {
        id: newDrawerId(),
        name: input.name.trim(),
        icon: input.icon,
        color: input.color,
      };
      persist({ ...state, drawers: [...state.drawers, drawer] });
      return drawer.id;
    },
    [state, persist],
  );

  const updateDrawer = useCallback(
    (id: string, patch: DrawerPatch) => {
      persist({
        ...state,
        drawers: state.drawers.map((drawer) =>
          drawer.id === id
            ? {
                ...drawer,
                ...patch,
                name:
                  patch.name !== undefined ? patch.name.trim() : drawer.name,
              }
            : drawer,
        ),
      });
    },
    [state, persist],
  );

  const deleteDrawer = useCallback(
    (id: string) => {
      const membership: Record<string, string> = {};
      for (const [cardId, drawerId] of Object.entries(state.membership)) {
        if (drawerId !== id) membership[cardId] = drawerId;
      }
      persist({
        drawers: state.drawers.filter((drawer) => drawer.id !== id),
        membership,
      });
    },
    [state, persist],
  );

  const moveCard = useCallback(
    (cardId: string, drawerId: string | null) => {
      const membership = { ...state.membership };
      if (drawerId === null) {
        delete membership[cardId];
      } else {
        membership[cardId] = drawerId;
      }
      persist({ ...state, membership });
    },
    [state, persist],
  );

  // 批量移动（2026-09-04，req3）：多选右键「移动到抽屉」把选中卡片一次性归入
  // 目标（null=未分组）。单次 persist 写入全部归属，避免逐张 moveCard 各读同一
  // stale state 相互覆盖（后者只会保留最后一张的改动）。
  const moveCards = useCallback(
    (cardIds: string[], drawerId: string | null) => {
      const membership = { ...state.membership };
      for (const cardId of cardIds) {
        if (drawerId === null) {
          delete membership[cardId];
        } else {
          membership[cardId] = drawerId;
        }
      }
      persist({ ...state, membership });
    },
    [state, persist],
  );

  // 收起/展开一个抽屉（2026-09-04）：只翻 hidden 标志，抽屉定义与卡片归属不动。
  const setDrawerHidden = useCallback(
    (id: string, hidden: boolean) => {
      persist({
        ...state,
        drawers: state.drawers.map((drawer) =>
          drawer.id === id ? { ...drawer, hidden } : drawer,
        ),
      });
    },
    [state, persist],
  );

  // 从 -> 下拉点击一个抽屉（2026-09-04）：取消收起并移到最前（紧跟「我的条目」
  // 标题）。单次 persist 同时完成两件事，避免与 setDrawerHidden 各自读同一份
  // stale state 相互覆盖；重建对象时不带 hidden 键，保持读写往返保真。
  const revealDrawerToFront = useCallback(
    (id: string) => {
      const target = state.drawers.find((drawer) => drawer.id === id);
      if (!target) return;
      const revealed: CardDrawer = {
        id: target.id,
        name: target.name,
        icon: target.icon,
        color: target.color,
      };
      persist({
        ...state,
        drawers: [
          revealed,
          ...state.drawers.filter((drawer) => drawer.id !== id),
        ],
      });
    },
    [state, persist],
  );

  return {
    drawers: state.drawers,
    membership: state.membership,
    drawerOf,
    createDrawer,
    updateDrawer,
    deleteDrawer,
    setDrawerHidden,
    revealDrawerToFront,
    moveCard,
    moveCards,
  };
}
