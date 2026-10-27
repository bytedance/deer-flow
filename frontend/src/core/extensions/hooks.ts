"use client";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { useAuth } from "@/core/auth/AuthProvider";

import { fetchFrontendExtensions, frontendExtensionsQueryKey } from "./api";
import { loadFrontendExtensions } from "./registry";
import { conversationText, latestVisibleAnswer } from "./services";

export function useFrontendExtensions() {
  const { user } = useAuth();
  return useQuery({
    queryKey: [...frontendExtensionsQueryKey, user?.id],
    queryFn: async () =>
      loadFrontendExtensions(await fetchFrontendExtensions()),
    enabled: !!user,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
}
/** Eagerly capture the page's plugin set, even before its first chat is opened. */
export function ExtensionPageBootstrap() {
  useFrontendExtensions();
  return null;
}
export function useFrontendServices() {
  return {
    conversationText,
    latestVisibleAnswer,
    showMessage: (message: string) => toast.message(message),
  };
}
