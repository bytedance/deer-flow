import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { GatewayApiError } from "@/core/api/errors";

import {
  loadAgentTracing,
  loadTracingProfiles,
  saveAgentTracing,
  saveTracingProfile,
} from "./api";
import type {
  SaveAgentTracingRequest,
  SaveTracingProfileRequest,
} from "./types";

export function useTracingProfiles(userId: string | null | undefined) {
  return useQuery({
    queryKey: ["tracing-profiles", userId],
    queryFn: ({ signal }) => loadTracingProfiles(signal),
    enabled: !!userId,
    retry: false,
  });
}

export function useAgentTracing(
  name: string,
  userId: string | null | undefined,
) {
  return useQuery({
    queryKey: ["agent-tracing", userId, name],
    queryFn: ({ signal }) => loadAgentTracing(name, signal),
    enabled: !!userId && !!name,
    retry: false,
  });
}

export function useSaveAgentTracing(name: string, userId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SaveAgentTracingRequest) => saveAgentTracing(name, body),
    onSuccess: (data) => {
      client.setQueryData(["agent-tracing", userId, name], data);
    },
  });
}

export function useSaveTracingProfile(userId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string | null;
      body: SaveTracingProfileRequest;
    }) => saveTracingProfile(id, body),
    onError: async (error) => {
      if (error instanceof GatewayApiError && error.status === 409) {
        await client.invalidateQueries({
          queryKey: ["tracing-profiles", userId],
        });
      }
    },
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["tracing-profiles", userId] }),
        client.invalidateQueries({ queryKey: ["agent-tracing", userId] }),
      ]);
    },
  });
}
