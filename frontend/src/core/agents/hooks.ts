import { useMemo } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createAgent,
  deleteAgent,
  forkAgent,
  getAgent,
  listAgents,
  setAgentEnabled,
  updateAgent,
} from "./api";
import type {
  Agent,
  AgentGroup,
  CreateAgentRequest,
  UpdateAgentRequest,
} from "./types";

export function useAgents() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents"],
    queryFn: () => listAgents(),
  });
  return { agents: data ?? [], isLoading, error };
}

export function useGroupedAgents() {
  const { agents, isLoading, error } = useAgents();

  const groups = useMemo((): AgentGroup[] => {
    const builtin: Agent[] = [];
    const tenant: Agent[] = [];
    const user: Agent[] = [];

    for (const agent of agents) {
      if (agent.source === "builtin") builtin.push(agent);
      else if (agent.source === "tenant") tenant.push(agent);
      else user.push(agent);
    }

    const result: AgentGroup[] = [];
    if (user.length > 0) result.push({ label: "My Agents", source: "user", agents: user });
    if (tenant.length > 0) result.push({ label: "Team Agents", source: "tenant", agents: tenant });
    if (builtin.length > 0) result.push({ label: "Built-in", source: "builtin", agents: builtin });
    return result;
  }, [agents]);

  return { groups, agents, isLoading, error };
}

export function useAgent(name: string | null | undefined) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents", name],
    queryFn: () => getAgent(name!),
    enabled: !!name,
  });
  return { agent: data ?? null, isLoading, error };
}

export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateAgentRequest) => createAgent(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useUpdateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      request,
    }: {
      name: string;
      request: UpdateAgentRequest;
    }) => updateAgent(name, request),
    onSuccess: (_data, { name }) => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents", name] });
    },
  });
}

export function useDeleteAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => deleteAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useSetAgentEnabled() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      setAgentEnabled(name, enabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useForkAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => forkAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}
