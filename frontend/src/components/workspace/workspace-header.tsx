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
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state } = useSidebar();
  const pathname = usePathname();
  const { user } = useAuth();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex min-h-12 flex-col justify-center py-1",
          className,
        )}
      >
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div className="text-primary block pt-1 font-serif group-hover/workspace-header:hidden">
              DF
            </div>
            <SidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <div className="ml-2 min-w-0 flex-1">
              {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
                <Link href="/" className="text-primary font-serif">
                  DeerFlow
                </Link>
              ) : (
                <div className="text-primary cursor-default font-serif">
                  DeerFlow
                </div>
              )}
              {user && (
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-[11px] text-muted-foreground">
                    {user.email}
                  </span>
                  {user.system_role === "admin" && (
                    <span className="shrink-0 rounded bg-blue-100 px-1 py-px text-[9px] font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-200">
                      admin
                    </span>
                  )}
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
