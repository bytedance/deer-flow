"use client";

import { useQuery } from "@tanstack/react-query";

import { loadAppConfig, type AppConfig } from "./api";

const DEFAULT_APP_CONFIG: AppConfig = {
  ui: {
    show_bash_script: true,
  },
};

export function useAppConfig() {
  const { data } = useQuery({
    queryKey: ["app-config"],
    queryFn: loadAppConfig,
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: false,
  });
  return data ?? DEFAULT_APP_CONFIG;
}
