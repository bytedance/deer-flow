"use client";

import { BookOpenIcon, BotIcon, ChevronDownIcon, MessagesSquare } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useAgents } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "sidebar-agents-collapsed";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { agents } = useAgents();
  const enabledAgents = agents.filter((a) => a.enabled);

  const [agentsOpen, setAgentsOpen] = useState(() => {
    if (typeof window === "undefined") return true;
    return localStorage.getItem(STORAGE_KEY) !== "true";
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, agentsOpen ? "false" : "true");
  }, [agentsOpen]);

  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/chats"} asChild>
            <Link className="text-muted-foreground" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>

        <SidebarMenuItem>
          <Collapsible open={agentsOpen} onOpenChange={setAgentsOpen}>
            <CollapsibleTrigger asChild>
              <SidebarMenuButton>
                <BotIcon />
                <span className="flex-1 text-left">{t.sidebar.agents}</span>
                <ChevronDownIcon
                  className={cn(
                    "size-4 transition-transform",
                    !agentsOpen && "-rotate-90",
                  )}
                />
              </SidebarMenuButton>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <SidebarMenu className="ml-3 border-l pl-2">
                {enabledAgents.map((agent) => {
                  const href = `/workspace/agents/${agent.name}/chats/new`;
                  const isActive = pathname.startsWith(
                    `/workspace/agents/${agent.name}`,
                  );
                  return (
                    <SidebarMenuItem key={agent.name}>
                      <SidebarMenuButton isActive={isActive} asChild>
                        <Link className="text-muted-foreground" href={href}>
                          <span className="text-sm">
                            {agent.icon || <BotIcon className="size-4" />}
                          </span>
                          <span>{agent.display_name ?? agent.name}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </CollapsibleContent>
          </Collapsible>
        </SidebarMenuItem>

        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/knowledge-bases")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/knowledge-bases"
            >
              <BookOpenIcon />
              <span>{t.sidebar.knowledgeBases}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  );
}
