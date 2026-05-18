"use client";

import { MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

function BrandMark({ collapsed }: { collapsed: boolean }) {
  // Industrial product mark: solid square + sans wordmark.
  // Mirrors the lockup used on the login / setup screens so the brand stays
  // coherent between auth and the workspace.
  const square = (
    <span
      aria-hidden="true"
      className="bg-primary text-primary-foreground inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-[11px] font-bold tracking-tight"
    >
      E
    </span>
  );
  if (collapsed) {
    return square;
  }
  return (
    <span className="flex items-center gap-2">
      {square}
      <span className="text-foreground truncate text-sm font-semibold tracking-tight">
        EHM AI 工作台
      </span>
    </span>
  );
}

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state } = useSidebar();
  const pathname = usePathname();
  const collapsed = state === "collapsed";
  return (
    <>
      <div
        className={cn(
          "group/workspace-header border-sidebar-border/60 flex min-h-14 flex-col justify-center border-b py-2",
          className,
        )}
      >
        {collapsed ? (
          <div className="flex w-full cursor-pointer items-center justify-center">
            <div className="block group-hover/workspace-header:hidden">
              <BrandMark collapsed />
            </div>
            <SidebarTrigger className="hidden group-hover/workspace-header:block" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <div className="ml-2 min-w-0 flex-1">
              {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
                <Link href="/" className="block">
                  <BrandMark collapsed={false} />
                </Link>
              ) : (
                <div className="cursor-default">
                  <BrandMark collapsed={false} />
                </div>
              )}
            </div>
            <SidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/chats/new"}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/chats/new">
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
