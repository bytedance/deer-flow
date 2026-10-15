"use client";

import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useThreadActivity } from "@/core/threads/activity";

import { WorkspaceChannelsList } from "./channels/workspace-channels-list";
import { PluginNavigation } from "./plugin-navigation";
import { ProjectsSection } from "./projects-section";
import { RecentChatList } from "./recent-chat-list";
import { ThreadDeleteDialogProvider } from "./thread-delete-dialog";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceNavMenu } from "./workspace-nav-menu";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { open: isSidebarOpen } = useSidebar();
  // One activity poll per workspace (off unless the Gateway offers it): new
  // and changed server-created threads reach the thread lists without a
  // reload, and a read on another device clears their dots here.
  useThreadActivity();
  return (
    <ThreadDeleteDialogProvider>
      <Sidebar variant="sidebar" collapsible="icon" {...props}>
        <SidebarHeader className="py-0">
          <WorkspaceHeader />
        </SidebarHeader>
        <SidebarContent>
          <WorkspaceNavChatList />
          <PluginNavigation />
          <WorkspaceChannelsList />
          {isSidebarOpen && (
            <>
              <ProjectsSection />
              <RecentChatList />
            </>
          )}
        </SidebarContent>
        <SidebarFooter>
          <WorkspaceNavMenu />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
    </ThreadDeleteDialogProvider>
  );
}
