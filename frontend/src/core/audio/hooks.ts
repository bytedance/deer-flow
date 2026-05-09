import { useMutation, useQuery } from "@tanstack/react-query";

import {
  loadAudioInputConfig,
  type AudioInputConfigResponse,
  transcribeAudio,
  type AudioTranscriptionOptions,
  type AudioTranscriptionResponse,
} from "./api";

export interface AudioTranscriptionInput extends AudioTranscriptionOptions {
  file: File;
}

export function useAudioInputConfig({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<AudioInputConfigResponse, Error>({
    queryKey: ["audio", "config"],
    queryFn: () => loadAudioInputConfig(),
    enabled,
    refetchOnWindowFocus: false,
  });
}

export function useAudioTranscription(threadId: string) {
  return useMutation<
    AudioTranscriptionResponse,
    Error,
    AudioTranscriptionInput
  >({
    mutationFn: ({ file, ...options }) =>
      transcribeAudio(threadId, file, options),
  });
}
