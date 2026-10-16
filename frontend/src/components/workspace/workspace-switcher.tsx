"use client";

import {
  Building2Icon,
  ChevronsUpDownIcon,
  HomeIcon,
  LayersIcon,
} from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import Link from "@/components/workspace/workspace-link";
import { useI18n } from "@/core/i18n/hooks";
import { useWorkspaceContext } from "@/core/workspaces/context";

/** This control chooses a locator; WorkspaceSession confirms all authority. */
export function WorkspaceSwitcher() {
  const controls = useWorkspaceContext();
  const { t } = useI18n();
  if (!controls) return null;
  const { state } = controls;
  const words = t.workspace.spaceSwitcher;
  const current = state.workspaces.find(
    (workspace) => workspace.id === state.active?.scope.workspaceId,
  );
  const label =
    current?.name ??
    (state.status === "loading" ? words.loading : words.unavailable);
  const Icon =
    current?.kind === "team" ? Building2Icon : current ? HomeIcon : LayersIcon;
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              disabled={state.workspaces.length === 0}
              aria-label={words.label + ": " + label}
              aria-busy={state.status === "loading"}
              tooltip={words.label + ": " + label}
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <Icon className="size-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate">{label}</span>
              <ChevronsUpDownIcon className="text-muted-foreground ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            sideOffset={4}
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
          >
            <DropdownMenuLabel>{words.label}</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={current?.id ?? ""}
              onValueChange={(id) => {
                void controls.select(id);
              }}
            >
              {state.workspaces.map((workspace) => (
                <DropdownMenuRadioItem
                  key={workspace.id}
                  value={workspace.id}
                  aria-label={
                    (workspace.kind === "personal"
                      ? words.personal
                      : words.team) +
                    ": " +
                    workspace.name
                  }
                >
                  <span className="min-w-0 flex-1 truncate">
                    {workspace.name}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {workspace.kind === "personal"
                      ? words.personal
                      : words.team}
                  </span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
      {state.status === "error" && (
        <SidebarMenuItem>
          <p role="alert" className="text-muted-foreground px-2 text-sm">
            {state.error === "authentication_required"
              ? words.authRequired
              : words.error}
          </p>
          <SidebarMenuButton
            onClick={() => {
              void controls.refresh();
            }}
          >
            {words.retry}
          </SidebarMenuButton>
          <SidebarMenuButton
            onClick={() => {
              void controls.select();
            }}
          >
            {words.personalAction}
          </SidebarMenuButton>
          <SidebarMenuButton asChild>
            <Link href={controls.signInHref ?? "/login"} prefetch={false}>
              {t.login.signIn}
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      )}
    </SidebarMenu>
  );
}
