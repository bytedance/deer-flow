import { useQuery } from "@tanstack/react-query";

import { fetchFeatures } from "@/core/features/api";
import { isStaticWebsiteOnly } from "@/core/static-mode";

export function useVoiceInputCapability(
  viewerId: string | undefined,
  enabled: boolean,
) {
  const available = enabled && !isStaticWebsiteOnly();
  const query = useQuery({
    queryKey: ["features", "voice_input", viewerId],
    queryFn: ({ signal }) => fetchFeatures(signal),
    enabled: available,
    staleTime: 0,
    retry: false,
    refetchOnMount: true,
  });
  const feature =
    available && query.isSuccess ? query.data?.voice_input : undefined;
  if (
    feature?.enabled !== true ||
    !Number.isInteger(feature.max_audio_bytes) ||
    feature.max_audio_bytes <= 0 ||
    !Number.isInteger(feature.max_duration_seconds) ||
    feature.max_duration_seconds <= 0
  )
    return null;
  return feature;
}
