"use client";

import { MessageSquarePlus, VenetianMaskIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useIncognitoFeature } from "@/core/features/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { useWorkspaceSidebarExpanded } from "./workspace-sidebar-frame";
import { WorkspaceSidebarTrigger } from "./workspace-sidebar-trigger";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { isMobile } = useSidebar();
  const isSidebarOpen = useWorkspaceSidebarExpanded();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { enabled: incognitoEnabled } = useIncognitoFeature();
  const isNewChatPath = pathname === "/workspace/chats/new";
  const isIncognitoNew =
    isNewChatPath && searchParams.get("incognito") === "true";
  // A static demo has no Gateway, so the entry would lead to a dead page.
  const showIncognito =
    incognitoEnabled && env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex h-12 flex-col justify-center",
          className,
        )}
      >
        {!isSidebarOpen ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div
              className={cn(
                "text-primary block pt-1 font-serif group-hover/workspace-header:hidden",
                isMobile && "hidden",
              )}
            >
              DF
            </div>
            <WorkspaceSidebarTrigger
              className={cn(
                "pl-2",
                !isMobile && "hidden group-hover/workspace-header:block",
              )}
            />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link href="/" className="text-primary ml-2 font-serif">
                DeerFlow
              </Link>
            ) : (
              <div className="text-primary ml-2 cursor-default font-serif">
                DeerFlow
              </div>
            )}
            <WorkspaceSidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={isNewChatPath && !isIncognitoNew}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/chats/new">
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {showIncognito && (
          <SidebarMenuItem>
            <SidebarMenuButton isActive={isIncognitoNew} asChild>
              <Link
                className="text-muted-foreground"
                href="/workspace/chats/new?incognito=true"
              >
                <VenetianMaskIcon size={16} />
                <span>{t.incognito.entry}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
      </SidebarMenu>
    </>
  );
}
