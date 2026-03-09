import { useMemo } from "react";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import type { AgentThread } from "@/core/threads/types";

import { ThreadItem } from "./thread-item";

interface DateGroupedThreadListProps {
  threads: AgentThread[];
  onRename: (threadId: string, currentTitle: string) => void;
  onDelete: (threadId: string) => void;
  onShare: (threadId: string) => void;
  onAssignToProject: (threadId: string) => void;
}

interface DateGroup {
  key: string;
  label: string;
  threads: AgentThread[];
}

function groupThreadsByDate(
  threads: AgentThread[],
  labels: {
    today: string;
    yesterday: string;
    lastSevenDays: string;
    lastThirtyDays: string;
    older: string;
  },
): DateGroup[] {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart);
  yesterdayStart.setDate(yesterdayStart.getDate() - 1);
  const weekStart = new Date(todayStart);
  weekStart.setDate(weekStart.getDate() - 7);
  const monthStart = new Date(todayStart);
  monthStart.setDate(monthStart.getDate() - 30);

  const today: AgentThread[] = [];
  const yesterday: AgentThread[] = [];
  const lastSevenDays: AgentThread[] = [];
  const lastThirtyDays: AgentThread[] = [];
  const older: AgentThread[] = [];

  for (const thread of threads) {
    const date = new Date(thread.created_at);
    if (date >= todayStart) {
      today.push(thread);
    } else if (date >= yesterdayStart) {
      yesterday.push(thread);
    } else if (date >= weekStart) {
      lastSevenDays.push(thread);
    } else if (date >= monthStart) {
      lastThirtyDays.push(thread);
    } else {
      older.push(thread);
    }
  }

  const sortByUpdated = (a: AgentThread, b: AgentThread) =>
    new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();

  const allGroups: [string, string, AgentThread[]][] = [
    ["today", labels.today, today],
    ["yesterday", labels.yesterday, yesterday],
    ["lastSevenDays", labels.lastSevenDays, lastSevenDays],
    ["lastThirtyDays", labels.lastThirtyDays, lastThirtyDays],
    ["older", labels.older, older],
  ];

  return allGroups
    .filter(([, , threads]) => threads.length > 0)
    .map(([key, label, threads]) => ({
      key,
      label,
      threads: threads.sort(sortByUpdated),
    }));
}

export function DateGroupedThreadList({
  threads,
  onRename,
  onDelete,
  onShare,
  onAssignToProject,
}: DateGroupedThreadListProps) {
  const { t } = useI18n();

  const groups = useMemo(
    () =>
      groupThreadsByDate(threads, {
        today: t.sidebar.today,
        yesterday: t.sidebar.yesterday,
        lastSevenDays: t.sidebar.lastSevenDays,
        lastThirtyDays: t.sidebar.lastThirtyDays,
        older: t.sidebar.older,
      }),
    [threads, t],
  );

  if (threads.length === 0) {
    return null;
  }

  return (
    <>
      {groups.map((group) => (
        <SidebarGroup key={group.key} className="py-0">
          <SidebarGroupLabel className="text-muted-foreground/70 text-xs">
            {group.label}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <div className="flex w-full flex-col gap-0.5">
                {group.threads.map((thread) => (
                  <ThreadItem
                    key={thread.thread_id}
                    thread={thread}
                    onRename={onRename}
                    onDelete={onDelete}
                    onShare={onShare}
                    onAssignToProject={onAssignToProject}
                  />
                ))}
              </div>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      ))}
    </>
  );
}
