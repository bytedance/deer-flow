"use client";

import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
} from "@/components/ui/sidebar";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { SidebarThreadList } from "./sidebar/sidebar-thread-list";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavMenu } from "./workspace-nav-menu";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  return (
    <>
      <Sidebar
        variant="sidebar"
        collapsible="icon"
        className={cn(env.IS_ELECTRON && "!top-10")}
        style={
          env.IS_ELECTRON ? { height: "calc(100vh - 2.5rem)" } : undefined
        }
        {...props}
      >
        <SidebarHeader className="py-0">
          <WorkspaceHeader />
        </SidebarHeader>
        <SidebarContent>
          <SidebarThreadList />
        </SidebarContent>
        <SidebarFooter>
          <WorkspaceNavMenu />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
    </>
  );
}
