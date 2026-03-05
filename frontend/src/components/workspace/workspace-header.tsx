import { MessageSquarePlus } from "lucide-react";
import { Link, useLocation } from "react-router";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useAppConfig } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { brand } = useAppConfig();
  const { state } = useSidebar();
  const location = useLocation();
  return (
    <>
      {/* In Electron, brand and trigger live in WorkspaceTitleBar */}
      {!env.IS_ELECTRON && (
        <div
          className={cn(
            "group/workspace-header flex h-12 flex-col justify-center",
            className,
          )}
        >
          {state === "collapsed" ? (
            // Non-Electron collapsed: TT logo + hover-to-reveal trigger
            <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
              <div className="gradient-text block pt-1 font-serif group-hover/workspace-header:hidden">
                TT
              </div>
              <SidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
            </div>
          ) : (
            // Non-Electron expanded: brand + trigger
            <div className="flex items-center">
              {env.VITE_STATIC_WEBSITE_ONLY === "true" ? (
                <Link to="/" className="gradient-text ml-2 font-serif">
                  {brand.name}
                </Link>
              ) : (
                <div className="gradient-text ml-2 cursor-default font-serif">
                  {brand.name}
                </div>
              )}
              <div className="flex-1" />
              <SidebarTrigger />
            </div>
          )}
        </div>
      )}
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={location.pathname === "/workspace/chats/new"}
            asChild
          >
            <Link className="text-muted-foreground" to="/workspace/chats/new">
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
