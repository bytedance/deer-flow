export type SpeechRecognitionErrorCode =
  | "aborted"
  | "audio-capture"
  | "bad-grammar"
  | "language-not-supported"
  | "network"
  | "no-speech"
  | "not-allowed"
  | "phrases-not-supported"
  | "service-not-allowed";

export type SpeechRecognitionErrorKind =
  | "cancelled"
  | "microphone_unavailable"
  | "permission_denied"
  | "unsupported_language"
  | "network"
  | "no_speech"
  | "unknown";

export type SpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

export type SpeechRecognitionEventLike = {
  results: SpeechRecognitionResultListLike;
};

export type SpeechRecognitionErrorEventLike = {
  error?: SpeechRecognitionErrorCode | string;
};

export type BrowserSpeechRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onend: (() => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechRecognitionWindow = Window &
  typeof globalThis & {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };

export type SpeechRecognitionAlternativeLike = {
  transcript?: string;
};

export type SpeechRecognitionResultLike = {
  0?: SpeechRecognitionAlternativeLike;
  isFinal: boolean;
  length: number;
};

export type SpeechRecognitionResultListLike = {
  [index: number]: SpeechRecognitionResultLike | undefined;
  length: number;
};

const DEFAULT_SPEECH_RECOGNITION_LANGUAGE = "en-US";
const SPEECH_RECOGNITION_LANGUAGE_ALLOWLIST = new Set([
  "de",
  "en",
  "es",
  "fr",
  "it",
  "ja",
  "ko",
  "pt",
  "zh",
]);

export function getSpeechRecognitionConstructor(
  value: unknown = globalThis,
): SpeechRecognitionConstructor | null {
  const maybeWindow = value as Partial<SpeechRecognitionWindow>;
  return (
    maybeWindow.SpeechRecognition ?? maybeWindow.webkitSpeechRecognition ?? null
  );
}

export function getSpeechRecognitionLanguage(locale: string): string {
  const normalized = normalizeBCP47Locale(locale);
  const language = normalized.split("-")[0]?.toLowerCase();

  if (language === "zh") {
    return "zh-CN";
  }
  if (language && SPEECH_RECOGNITION_LANGUAGE_ALLOWLIST.has(language)) {
    return normalized;
  }
  return DEFAULT_SPEECH_RECOGNITION_LANGUAGE;
}

export function shouldRestartSpeechRecognition(
  lastError: SpeechRecognitionErrorKind | null,
): boolean {
  return lastError === null || lastError === "no_speech";
}

export function readSpeechRecognitionTranscript(
  results: SpeechRecognitionResultListLike,
): { finalText: string; interimText: string; text: string } {
  let finalText = "";
  let interimText = "";

  for (const result of Array.from(
    { length: results.length },
    (_, index) => results[index],
  )) {
    const transcript = result?.[0]?.transcript ?? "";
    if (result?.isFinal) {
      finalText += transcript;
    } else {
      interimText += transcript;
    }
  }

  return {
    finalText: normalizeSpeechTranscript(finalText),
    interimText: normalizeSpeechTranscript(interimText),
    text: normalizeSpeechTranscript(joinSpeechSegments(finalText, interimText)),
  };
}

// Providers are expected to pad result boundaries with whitespace, but some
// (WebKit, several Android WebViews) trim final transcripts. Re-insert the
// separator only where gluing is certainly wrong: two ASCII word characters
// meeting at the boundary. CJK dictation relies on the glue, so it must not
// gain a space; provider-emitted boundary whitespace also passes through
// unchanged since it fails the word-character test.
function joinSpeechSegments(finalText: string, interimText: string): string {
  if (!finalText || !interimText) {
    return `${finalText}${interimText}`;
  }
  const tail = finalText[finalText.length - 1]!;
  const head = interimText[0]!;
  if (/[A-Za-z0-9]/.test(tail) && /[A-Za-z0-9]/.test(head)) {
    return `${finalText} ${interimText}`;
  }
  return `${finalText}${interimText}`;
}

export function appendSpeechTranscript(baseText: string, transcript: string) {
  const cleanTranscript = normalizeSpeechTranscript(transcript);
  if (!cleanTranscript) {
    return baseText;
  }

  const cleanBase = baseText.trimEnd();
  if (!cleanBase) {
    return cleanTranscript;
  }

  return `${cleanBase} ${cleanTranscript}`;
}

export function normalizeSpeechTranscript(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

export function mapSpeechRecognitionError(
  error: SpeechRecognitionErrorCode | string | undefined,
): SpeechRecognitionErrorKind {
  switch (error) {
    case "aborted":
      return "cancelled";
    case "audio-capture":
      return "microphone_unavailable";
    case "not-allowed":
    case "service-not-allowed":
      return "permission_denied";
    case "language-not-supported":
      return "unsupported_language";
    case "network":
      return "network";
    case "no-speech":
      return "no_speech";
    default:
      return "unknown";
  }
}

function normalizeBCP47Locale(locale: string): string {
  const trimmed = locale.trim();
  if (!trimmed) {
    return DEFAULT_SPEECH_RECOGNITION_LANGUAGE;
  }
  try {
    return Intl.getCanonicalLocales(trimmed)[0] ?? trimmed;
  } catch {
    return DEFAULT_SPEECH_RECOGNITION_LANGUAGE;
  }
}
