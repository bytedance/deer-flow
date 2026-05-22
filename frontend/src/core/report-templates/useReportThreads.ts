import { useMemo } from "react";

import { useAgents } from "@/core/agents";
import { useThreads } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

/**
 * Collects agent names whose `tags` include `"report"`.
 * Pure function, exported for testing.
 */
export function collectReportAgentNames(agents: { name: string; tags?: string[] | null }[]): Set<string> {
  const names = new Set<string>();
  for (const agent of agents) {
    if (agent.tags?.includes("report")) {
      names.add(agent.name);
    }
  }
  return names;
}

/**
 * Filters threads to only those from report agents, sorted by `updated_at`
 * descending. Pure function, exported for testing.
 */
export function filterReportThreads(
  threads: AgentThread[],
  reportAgentNames: Set<string>,
  limit?: number,
): AgentThread[] {
  const filtered = threads.filter((t) => {
    const agentName = t.metadata?.agent_name;
    return typeof agentName === "string" && reportAgentNames.has(agentName);
  });
  filtered.sort((a, b) => {
    const da = a.updated_at ?? "";
    const db = b.updated_at ?? "";
    return db.localeCompare(da);
  });
  return limit != null ? filtered.slice(0, limit) : filtered;
}

/**
 * Returns threads that were created through report agents (agents with
 * `tags` containing `"report"`), sorted by `updated_at` descending.
 *
 * Shares the same `useThreads` query cache as `RecentChatList` when
 * called without metadata filters, avoiding duplicate API calls.
 */
export function useReportThreads(limit?: number): {
  threads: AgentThread[];
  isLoading: boolean;
  error: Error | null;
} {
  const { agents } = useAgents();
  const { data: allThreads, isLoading, error } = useThreads();

  const reportAgentNames = useMemo(() => collectReportAgentNames(agents), [agents]);

  const threads = useMemo(() => allThreads ?? [], [allThreads]);

  const reportThreads = useMemo(
    () => filterReportThreads(threads, reportAgentNames, limit),
    [threads, reportAgentNames, limit],
  );

  return { threads: reportThreads, isLoading, error };
}
