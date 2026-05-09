import { fetchGateway } from "../api";
import { getBackendBaseURL } from "../config";
import type { UploadedFileInfo } from "../uploads/api";

export interface AudioTranscriptionOptions {
  locale?: string;
  attachOriginal?: boolean;
}

export interface AudioInputConfigResponse {
  enabled: boolean;
  microphone_enabled: boolean;
  file_transcription_enabled: boolean;
  default_locale: string;
  supported_locales: string[];
  accepted_mime_types: string[];
  max_file_size: number;
}

export interface AudioTranscriptionResponse {
  success: boolean;
  transcript: string;
  language?: string;
  duration_ms?: number;
  file?: UploadedFileInfo;
}

async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = await response.json().catch(() => ({ detail: fallback }));
  return error.detail ?? fallback;
}

export async function loadAudioInputConfig(): Promise<AudioInputConfigResponse> {
  const response = await fetchGateway(`${getBackendBaseURL()}/api/audio/config`);

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Failed to load audio config"));
  }

  return response.json();
}

export async function transcribeAudio(
  threadId: string,
  file: File,
  options?: AudioTranscriptionOptions,
): Promise<AudioTranscriptionResponse> {
  const formData = new FormData();
  formData.append("file", file);

  if (options?.locale) {
    formData.append("locale", options.locale);
  }

  if (typeof options?.attachOriginal === "boolean") {
    formData.append("attach_original", String(options.attachOriginal));
  }

  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/threads/${threadId}/audio/transcriptions`,
    {
      method: "POST",
      body: formData,
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Transcription failed"));
  }

  return response.json();
}
