"use client";

import {
  BookOpenIcon,
  BotIcon,
  BugIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  FileTextIcon,
  HistoryIcon,
  MessagesSquare,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ComponentType, useEffect, useMemo, useState } from "react";

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
import { type Agent, type NavItem, useAgentChildren, useAgents } from "@/core/agents";
import { useClosureRefresh, useClosureSummary } from "@/core/closed-loop";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AgentChildSelector } from "./agent-child-selector";

const STORAGE_KEY = "sidebar-agents-collapsed";

const NAV_ICON_MAP: Record<string, ComponentType<{ className?: string }>> = {
  FileText: FileTextIcon,
  History: HistoryIcon,
  BookOpen: BookOpenIcon,
  Bug: BugIcon,
};

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

  const dynamicNavItems = useMemo(() => {
    const items: (NavItem & { key: string })[] = [];
    for (const agent of agents) {
      if (agent.enabled && agent.nav_items?.length) {
        for (const item of agent.nav_items) {
          items.push({ ...item, key: `${agent.name}:${item.path}` });
        }
      }
    }
    return items;
  }, [agents]);

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

        <ClosedLoopNavItem active={pathname.startsWith("/workspace/closed-loop")} />

        {dynamicNavItems.map((item) => {
          const Icon = NAV_ICON_MAP[item.icon] ?? FileTextIcon;
          return (
            <SidebarMenuItem key={item.key}>
              <SidebarMenuButton
                isActive={pathname.startsWith(item.path)}
                asChild
              >
                <Link className="text-muted-foreground" href={item.path}>
                  <Icon className="size-4" />
                  <span>{item.label}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          );
        })}

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

function ClosedLoopNavItem({ active }: { active: boolean }) {
  useClosureRefresh();
  const { summary } = useClosureSummary({ refetchInterval: 60_000 });
  const open = summary?.open ?? 0;
  const overdue = summary?.overdue ?? 0;
  return (
    <SidebarMenuItem>
      <SidebarMenuButton isActive={active} asChild>
        <Link className="text-muted-foreground" href="/workspace/closed-loop">
          <CheckCircle2Icon />
          <span className="flex-1">闭环管理</span>
          {overdue > 0 && (
            <span className="rounded-full bg-red-500/15 px-1.5 py-0.5 text-[10px] font-medium text-red-700 dark:text-red-300">
              {overdue}
            </span>
          )}
          {overdue === 0 && open > 0 && (
            <span className="rounded-full bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:text-blue-300">
              {open}
            </span>
          )}
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
