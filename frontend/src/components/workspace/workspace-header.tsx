"use client";

import { MessageSquarePlus } from "@/components/ui/icons";
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
  if (collapsed) {
    return null;
  }
  return (
    <span className="flex min-w-0 items-center">
      <span className="text-foreground truncate text-sm font-semibold tracking-tight">
        AI工作台
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
            <SidebarTrigger />
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
