"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          isActive={pathname === "/workspace/chats"}
          asChild
          className="font-medium"
        >
          <Link href="/workspace/chats">
            <Search className="size-4" />
            <span>{t.common.search}</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
