import { useQuery } from "@tanstack/react-query";

import { fetchModuleFlags } from "./api";

export function useModuleFlags() {
  return useQuery({
    queryKey: ["module-flags"],
    queryFn: fetchModuleFlags,
    staleTime: 60_000,
    retry: 1,
  });
}
