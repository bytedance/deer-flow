"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission } from "@/core/auth/permissions";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { searchWorkspace, type SearchFilters } from "./api";

export function useWorkspaceSearch(
  input: string,
  filters: SearchFilters,
  enabled: boolean,
) {
  const { user } = useAuth();
  const [settled, setSettled] = useState(input);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(input), 250);
    return () => clearTimeout(timer);
  }, [input]);
  const query = input.trim();
  const ready = settled.trim() === query;
  const supported =
    !isStaticWebsiteOnly() && hasPermission(user, "threads:read");
  const result = useInfiniteQuery({
    queryKey: ["workspace-search", user?.id, query, filters],
    enabled: enabled && ready && supported,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      searchWorkspace(query, filters, pageParam, signal),
    getNextPageParam: (page) => page.cursor ?? undefined,
    staleTime: 0,
    gcTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (state) =>
      state.state.data?.pages.some((page) => page.indexing) ? 600 : false,
  });
  return {
    ...result,
    supported,
    waiting: !ready,
    items: ready
      ? (result.data?.pages.flatMap((page) => page.items) ?? [])
      : [],
  };
}
