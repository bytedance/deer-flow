"use client";

import { MoreHorizontalIcon, Settings2Icon } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useNavGateContext } from "@/components/workspace/nav-gate";
import { useI18n } from "@/core/i18n/hooks";
import { OPEN_SEARCH_EVENT } from "@/core/search/api";
import { useLocalSettings } from "@/core/settings/hooks";
import { resolveNavLayout } from "@/core/settings/nav-layout";

import { NAV_ITEMS, type NavItemDefinition } from "./nav-registry";

// The drag-and-drop dialog pulls in @dnd-kit; keep it out of the first paint.
const NavCustomizeDialog = dynamic(
  () => import("./nav-customize-dialog").then((mod) => mod.NavCustomizeDialog),
  { ssr: false },
);

function SearchShortcut() {
  const [shortcut, setShortcut] = useState("⌘K");
  useEffect(() => {
    setShortcut(navigator.userAgent.includes("Mac") ? "⌘K" : "Ctrl K");
  }, []);
  return (
    <kbd aria-hidden className="ml-auto text-xs">
      {shortcut}
    </kbd>
  );
}

interface NavItemButtonProps {
  item: NavItemDefinition;
  pathname: string;
  disabled: boolean;
  onSearch: () => void;
}

function NavItemButton({
  item,
  pathname,
  disabled,
  onSearch,
}: NavItemButtonProps) {
  const { t } = useI18n();
  const Icon = item.icon;
  const label = item.label(t);

  if (item.target.kind === "search") {
    return (
      <SidebarMenuButton
        onClick={onSearch}
        aria-label={label}
        tooltip={t.workspaceSearch.title}
        className="text-muted-foreground"
      >
        <Icon />
        <span>{label}</span>
        <SearchShortcut />
      </SidebarMenuButton>
    );
  }

  if (disabled) {
    const reason = item.disabledReason?.(t) ?? t.sidebar.featureDisabledTooltip;
    // Disabled: aria-disabled drives the sidebar CVA to suppress pointer
    // events on the button, so wrap it in a hoverable span that still
    // surfaces the "feature not enabled" tooltip for mouse users. The button
    // stays in the tab order (no tabIndex={-1}) and is wired via
    // aria-describedby to a visually-hidden reason, so keyboard and
    // screen-reader users also learn why it is disabled.
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          {/* cursor-not-allowed lives on the span (the element that still
              receives pointer events), not the inert button. */}
          <span className="block w-full cursor-not-allowed">
            <SidebarMenuButton
              className="text-muted-foreground/50"
              aria-disabled
              aria-describedby={`${item.key}-disabled-reason`}
            >
              <Icon />
              <span>{label}</span>
            </SidebarMenuButton>
            <span id={`${item.key}-disabled-reason`} className="sr-only">
              {reason}
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent side="right">{reason}</TooltipContent>
      </Tooltip>
    );
  }

  return (
    <SidebarMenuButton isActive={item.target.matches(pathname)} asChild>
      <Link className="text-muted-foreground" href={item.target.href}>
        <Icon />
        <span>{label}</span>
      </Link>
    </SidebarMenuButton>
  );
}

function MoreNavItem({
  item,
  disabled,
  active,
  onSearch,
  onNavigate,
}: {
  item: NavItemDefinition;
  disabled: boolean;
  active: boolean;
  onSearch: () => void;
  onNavigate: () => void;
}) {
  const { t } = useI18n();
  const Icon = item.icon;
  const label = item.label(t);

  if (disabled) {
    const reason = item.disabledReason?.(t) ?? t.sidebar.featureDisabledTooltip;
    // `disabled` on a menu item sets pointer-events: none, which also blocks
    // the tooltip. Keep the item hoverable and inert instead, matching the
    // greyed-out entry with its reason in the main menu.
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuItem
            aria-disabled
            aria-label={label}
            aria-describedby={`${item.key}-more-disabled-reason`}
            className="text-muted-foreground/50 focus:text-muted-foreground/50 [&_svg]:!text-muted-foreground/50 cursor-not-allowed focus:bg-transparent"
            onSelect={(event) => event.preventDefault()}
          >
            <Icon />
            <span>{label}</span>
            <span id={`${item.key}-more-disabled-reason`} className="sr-only">
              {reason}
            </span>
          </DropdownMenuItem>
        </TooltipTrigger>
        <TooltipContent side="right">{reason}</TooltipContent>
      </Tooltip>
    );
  }

  if (item.target.kind === "search") {
    return (
      <DropdownMenuItem onSelect={onSearch}>
        <Icon />
        <span>{label}</span>
      </DropdownMenuItem>
    );
  }

  return (
    <DropdownMenuItem
      asChild
      className={active ? "bg-accent text-accent-foreground" : undefined}
    >
      <Link
        href={item.target.href}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
      >
        <Icon />
        <span>{label}</span>
      </Link>
    </DropdownMenuItem>
  );
}

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const gate = useNavGateContext();
  const { setOpenMobile } = useSidebar();
  const [settings] = useLocalSettings();
  const [customizeOpen, setCustomizeOpen] = useState(false);

  const { primary, more } = resolveNavLayout(
    NAV_ITEMS,
    settings.navLayout,
    gate,
  );
  const currentInMore = more.some(
    (item) => item.target.kind === "link" && item.target.matches(pathname),
  );

  const openSearch = () => {
    setOpenMobile(false);
    window.dispatchEvent(new Event(OPEN_SEARCH_EVENT));
  };

  return (
    <>
      <SidebarGroup className="pt-1" data-workspace-nav="true">
        <SidebarMenu>
          {primary
            .filter((item) => item.showInMenu !== false)
            .map((item) => (
              <SidebarMenuItem key={item.key}>
                <NavItemButton
                  item={item}
                  pathname={pathname}
                  disabled={item.isDisabled?.(gate) === true}
                  onSearch={openSearch}
                />
              </SidebarMenuItem>
            ))}
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  className="text-muted-foreground"
                  isActive={currentInMore}
                >
                  <MoreHorizontalIcon />
                  <span>{t.sidebar.more}</span>
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" side="right" className="w-56">
                {more.length > 0 && (
                  <>
                    <DropdownMenuLabel>{t.sidebar.moreGroup}</DropdownMenuLabel>
                    {more.map((item) => (
                      <MoreNavItem
                        key={item.key}
                        item={item}
                        disabled={item.isDisabled?.(gate) === true}
                        active={
                          item.target.kind === "link" &&
                          item.target.matches(pathname)
                        }
                        onSearch={openSearch}
                        onNavigate={() => setOpenMobile(false)}
                      />
                    ))}
                    <DropdownMenuSeparator />
                  </>
                )}
                <DropdownMenuItem onSelect={() => setCustomizeOpen(true)}>
                  <Settings2Icon />
                  <span>{t.sidebar.customize}</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroup>
      {customizeOpen && (
        <NavCustomizeDialog open onOpenChange={setCustomizeOpen} />
      )}
    </>
  );
}
