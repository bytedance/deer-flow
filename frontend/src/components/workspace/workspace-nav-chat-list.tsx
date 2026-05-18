"use client";

import { BookOpenIcon, BotIcon, BugIcon, ChevronDownIcon, FileTextIcon, HistoryIcon, MessagesSquare } from "lucide-react";
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
import { type Agent, useAgentChildren, useAgents } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AgentChildSelector } from "./agent-child-selector";

const STORAGE_KEY = "sidebar-agents-collapsed";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { agents } = useAgents();
  const enabledAgents = agents
    .filter((a) => a.enabled && !a.parent)
    .sort((a, b) => (a.order ?? 999) - (b.order ?? 999));

  const [agentsOpen, setAgentsOpen] = useState(() => {
    if (typeof window === "undefined") return true;
    return localStorage.getItem(STORAGE_KEY) !== "true";
  });

  const [activeGroup, setActiveGroup] = useState<Agent | null>(null);
  const childAgents = useAgentChildren(activeGroup?.name);

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
                  const isGroup = agent.type === "group";
                  const isActive = pathname.startsWith(
                    `/workspace/agents/${agent.name}`,
                  );

                  if (isGroup) {
                    return (
                      <SidebarMenuItem key={agent.name}>
                        <SidebarMenuButton
                          isActive={isActive}
                          onClick={() => setActiveGroup(agent)}
                        >
                          <span className="text-sm">
                            {agent.icon ?? <BotIcon className="size-4" />}
                          </span>
                          <span>{agent.display_name ?? agent.name}</span>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    );
                  }

                  const href = `/workspace/agents/${agent.name}/chats/new`;
                  return (
                    <SidebarMenuItem key={agent.name}>
                      <SidebarMenuButton isActive={isActive} asChild>
                        <Link className="text-muted-foreground" href={href}>
                          <span className="text-sm">
                            {agent.icon ?? <BotIcon className="size-4" />}
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

        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/report-templates")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/report-templates"
            >
              <FileTextIcon />
              <span>报告模板</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>

        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/report-runs")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/report-runs"
            >
              <HistoryIcon />
              <span>报告历史</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>

        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/debug/a2ui")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/debug/a2ui"
            >
              <BugIcon />
              <span>{t.sidebar.a2uiDebug}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>

      <AgentChildSelector
        open={activeGroup !== null}
        agents={childAgents}
        title={activeGroup?.display_name ?? activeGroup?.name}
        description={activeGroup?.description ?? undefined}
        onClose={() => setActiveGroup(null)}
      />
    </SidebarGroup>
  );
}
