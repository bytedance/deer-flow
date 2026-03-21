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

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state } = useSidebar();
  const pathname = usePathname();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex h-12 flex-col justify-center",
          className,
        )}
      >
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div 
              className="text-primary block font-bold text-lg group-hover/workspace-header:hidden"
              suppressHydrationWarning
              translate="no"
            >
              DF
            </div>
            <SidebarTrigger className="hidden group-hover/workspace-header:block" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 px-1">
            <div className="text-primary flex items-center gap-2 font-bold text-xl tracking-tight" translate="no">
              <span className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-lg shadow-lg">🦌</span>
              DeerFlow
            </div>
            <SidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu className="px-2 mt-2">
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/chats/new"}
            asChild
            className={cn(
              "glass-button rounded-xl py-6 hover:bg-primary/10 transition-all duration-300 border-white/5 shadow-sm",
              pathname === "/workspace/chats/new" ? "bg-primary/15 text-primary border-primary/20 shadow-primary/10" : "text-muted-foreground"
            )}
          >
            <Link href="/workspace/chats/new">
              <MessageSquarePlus className="size-5" />
              <span className="font-semibold">{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
