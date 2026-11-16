import {
  BlocksIcon,
  BotIcon,
  CalendarClock,
  ChartColumn,
  MessageSquarePlus,
  MessagesSquare,
  SearchIcon,
  type LucideIcon,
} from "lucide-react";

import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import type { Translations } from "@/core/i18n";
import type { NavItemShape } from "@/core/settings/nav-layout";

export type NavTarget =
  | {
      kind: "link";
      href: string;
      matches: (pathname: string) => boolean;
    }
  | { kind: "search" };

/**
 * A sidebar entry: the layout rules from `nav-layout.ts` plus what the sidebar
 * needs to render it. Keep labels lazy so the registry does not depend on the
 * active locale.
 */
export interface NavItemDefinition extends NavItemShape {
  label: (t: Translations) => string;
  icon: LucideIcon;
  target: NavTarget;
  /**
   * False keeps the entry out of the sidebar menu group. The New chat entry
   * renders in the sidebar header instead, but still appears in the
   * customization dialog as the pinned row.
   */
  showInMenu?: boolean;
  /** Why the entry is inert while `isDisabled` is true. */
  disabledReason?: (t: Translations) => string;
}

/**
 * The core menu. To add an entry, append it here with an `order` higher than
 * the others and a `defaultGroup`; the sidebar and the customization dialog
 * pick it up without further changes. New chat stays pinned first; it renders
 * in the sidebar header and is not configurable.
 */
export const NAV_ITEMS: readonly NavItemDefinition[] = [
  {
    key: "new-chat",
    configurable: false,
    fixedPosition: "first",
    defaultGroup: "primary",
    order: -10,
    showInMenu: false,
    label: (t) => t.sidebar.newChat,
    icon: MessageSquarePlus,
    target: {
      kind: "link",
      href: "/workspace/chats/new",
      matches: (pathname) => pathname === "/workspace/chats/new",
    },
  },
  {
    key: "chats",
    configurable: true,
    defaultGroup: "primary",
    order: 0,
    label: (t) => t.sidebar.chats,
    icon: MessagesSquare,
    target: {
      kind: "link",
      href: "/workspace/chats",
      matches: (pathname) => pathname === "/workspace/chats",
    },
  },
  {
    key: "search",
    configurable: true,
    defaultGroup: "primary",
    order: 10,
    label: (t) => t.workspaceSearch.open,
    icon: SearchIcon,
    target: { kind: "search" },
  },
  {
    key: "agents",
    configurable: true,
    defaultGroup: "primary",
    order: 20,
    label: (t) => t.sidebar.agents,
    icon: BotIcon,
    target: {
      kind: "link",
      href: "/workspace/agents",
      matches: (pathname) => pathname.startsWith("/workspace/agents"),
    },
    isDisabled: (ctx) => !ctx.agentsEnabled,
    disabledReason: (t) => t.sidebar.featureDisabledTooltip,
  },
  {
    key: "scheduled-tasks",
    configurable: true,
    defaultGroup: "primary",
    order: 30,
    label: (t) => t.sidebar.scheduledTasks,
    icon: CalendarClock,
    target: {
      kind: "link",
      href: "/workspace/scheduled-tasks",
      matches: (pathname) => pathname.startsWith("/workspace/scheduled-tasks"),
    },
  },
  {
    key: "usage",
    configurable: true,
    defaultGroup: "primary",
    order: 40,
    label: (t) => t.usage.title,
    icon: ChartColumn,
    target: {
      kind: "link",
      href: "/workspace/usage",
      matches: (pathname) => pathname.startsWith("/workspace/usage"),
    },
    isEnabled: (ctx) =>
      !!ctx.user &&
      hasPermission(ctx.user, PERMISSIONS.RUNS_READ) &&
      !ctx.staticMode,
  },
  {
    key: "capabilities",
    configurable: true,
    defaultGroup: "primary",
    order: 50,
    label: (t) => t.capabilities.title,
    icon: BlocksIcon,
    target: {
      kind: "link",
      href: "/workspace/capabilities",
      matches: (pathname) => pathname.startsWith("/workspace/capabilities"),
    },
  },
];
