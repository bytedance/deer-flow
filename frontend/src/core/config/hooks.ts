import { useQuery } from "@tanstack/react-query";

import { loadAppConfig, type AppConfigResponse } from "./api";

export const DEFAULT_APP_CONFIG: AppConfigResponse = {
  brand: {
    name: "Dominium AI",
    website_url: "https://think-tank-ai.com",
    github_url: "https://github.com/thinktank-ai/thinktank-ai",
    support_email: "support@thinktank.ai",
  },
};

export function useAppConfig() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["appConfig"],
    queryFn: loadAppConfig,
    staleTime: 1000 * 60 * 5,
  });

  const config = data ?? DEFAULT_APP_CONFIG;

  return {
    config,
    brand: config.brand,
    isLoading,
    error,
  };
}
