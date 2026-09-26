import { useQuery } from "@tanstack/react-query";

import { loadSuggestionsConfig } from "./api";

export function useSuggestionsConfig() {
  return useQuery({
    queryKey: ["suggestionsConfig"],
    queryFn: loadSuggestionsConfig,
    staleTime: Infinity,
  });
}
