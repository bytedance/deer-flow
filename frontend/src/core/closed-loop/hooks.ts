import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createClosureTicket,
  getClosureNotificationsSummary,
  getClosureTicket,
  listClosureTicketEvents,
  listClosureTickets,
  transitionClosureTicket,
  updateClosureTicket,
} from "./client";
import type {
  ClosureTicket,
  CreateClosureTicketRequest,
  ListClosureTicketsParams,
  TransitionClosureTicketRequest,
  UpdateClosureTicketRequest,
} from "./types";

const QUERY_KEY_ROOT = "closure-tickets" as const;

export const closureQueryKeys = {
  all: [QUERY_KEY_ROOT] as const,
  list: (params?: ListClosureTicketsParams) =>
    [QUERY_KEY_ROOT, "list", params ?? {}] as const,
  detail: (id: string) => [QUERY_KEY_ROOT, "detail", id] as const,
  events: (id: string) => [QUERY_KEY_ROOT, "events", id] as const,
  summary: () => [QUERY_KEY_ROOT, "summary"] as const,
};

export function useClosureTickets(params?: ListClosureTicketsParams) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: closureQueryKeys.list(params),
    queryFn: () => listClosureTickets(params),
  });
  return {
    tickets: data?.items ?? [],
    meta: data?.meta,
    isLoading,
    error,
    refetch,
  };
}

export function useClosureTicket(ticketId: string | null | undefined) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ticketId
      ? closureQueryKeys.detail(ticketId)
      : [QUERY_KEY_ROOT, "detail", "__disabled__"],
    queryFn: () => getClosureTicket(ticketId!),
    enabled: Boolean(ticketId),
  });
  return { ticket: data ?? null, isLoading, error, refetch };
}

export function useClosureTicketEvents(ticketId: string | null | undefined) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ticketId
      ? closureQueryKeys.events(ticketId)
      : [QUERY_KEY_ROOT, "events", "__disabled__"],
    queryFn: () => listClosureTicketEvents(ticketId!),
    enabled: Boolean(ticketId),
  });
  return { events: data ?? [], isLoading, error, refetch };
}

export function useClosureSummary(opts?: { refetchInterval?: number }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: closureQueryKeys.summary(),
    queryFn: () => getClosureNotificationsSummary(),
    refetchInterval: opts?.refetchInterval,
  });
  return {
    summary: data ?? null,
    isLoading,
    error,
    refetch,
  };
}

export function useCreateClosureTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateClosureTicketRequest) =>
      createClosureTicket(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY_ROOT] });
    },
  });
}

export function useUpdateClosureTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      ticketId,
      request,
    }: {
      ticketId: string;
      request: UpdateClosureTicketRequest;
    }) => updateClosureTicket(ticketId, request),
    onMutate: async ({ ticketId, request }) => {
      await queryClient.cancelQueries({
        queryKey: closureQueryKeys.detail(ticketId),
      });
      const previous = queryClient.getQueryData<ClosureTicket>(
        closureQueryKeys.detail(ticketId),
      );
      if (previous) {
        queryClient.setQueryData<ClosureTicket>(
          closureQueryKeys.detail(ticketId),
          { ...previous, ...request, metadata: { ...previous.metadata, ...(request.metadata_patch ?? {}) } },
        );
      }
      return { previous };
    },
    onError: (_err, { ticketId }, ctx) => {
      if (ctx?.previous) {
        queryClient.setQueryData(closureQueryKeys.detail(ticketId), ctx.previous);
      }
    },
    onSettled: (_data, _err, { ticketId }) => {
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY_ROOT] });
      void queryClient.invalidateQueries({
        queryKey: closureQueryKeys.detail(ticketId),
      });
    },
  });
}

export function useTransitionClosureTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      ticketId,
      request,
    }: {
      ticketId: string;
      request: TransitionClosureTicketRequest;
    }) => transitionClosureTicket(ticketId, request),
    onSuccess: (data, { ticketId }) => {
      queryClient.setQueryData(closureQueryKeys.detail(ticketId), data);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY_ROOT] });
    },
  });
}
