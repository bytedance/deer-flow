import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type VoiceInputErrorCode =
  | "permission_denied"
  | "microphone_unavailable"
  | "unsupported"
  | "too_large"
  | "unavailable"
  | "no_speech"
  | "failed";

export class VoiceInputError extends Error {
  constructor(public readonly code: VoiceInputErrorCode) {
    super(code);
  }
}

export async function transcribeAudio(
  audio: Blob,
  signal: AbortSignal,
): Promise<string> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/voice-input/transcribe`,
    {
      method: "POST",
      headers: { "Content-Type": audio.type },
      body: audio,
      signal,
    },
  );
  if (!response.ok) {
    const code =
      response.status === 404
        ? "unavailable"
        : response.status === 413
          ? "too_large"
          : response.status === 422
            ? "no_speech"
            : "failed";
    throw new VoiceInputError(code);
  }
  const data: unknown = await response.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("text" in data) ||
    typeof data.text !== "string"
  ) {
    throw new VoiceInputError("failed");
  }
  const text = data.text.trim();
  if (!text) throw new VoiceInputError("no_speech");
  return text;
}

export function appendVoiceTranscript(
  draft: string,
  transcript: string,
): string {
  const text = transcript.trim();
  if (!text) return draft;
  return draft.trimEnd() ? `${draft.trimEnd()} ${text}` : text;
}
