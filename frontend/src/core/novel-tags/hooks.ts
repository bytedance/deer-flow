import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";

export function useNovelTags() {
  return useQuery<{ tags: string[] }>({
    queryKey: ["novel-tags"],
    queryFn: async () => {
      const response = await fetch(`${getBackendBaseURL()}/api/novel-tags/`);
      if (!response.ok) {
        throw new Error("Failed to fetch novel tags");
      }
      return response.json();
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}
