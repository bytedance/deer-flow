import { describe, expect, it } from "@rstest/core";

import {
  appendSpeechTranscript,
  getSpeechRecognitionConstructor,
  getSpeechRecognitionLanguage,
  mapSpeechRecognitionError,
  readSpeechRecognitionTranscript,
  shouldRestartSpeechRecognition,
  type SpeechRecognitionConstructor,
} from "@/core/voice-input/speech-recognition";

describe("speech recognition helpers", () => {
  it("prefers the standard constructor and falls back to webkit", () => {
    const standard = makeSpeechRecognitionConstructor();
    const webkit = makeSpeechRecognitionConstructor();

    expect(
      getSpeechRecognitionConstructor({
        SpeechRecognition: standard as unknown as SpeechRecognitionConstructor,
        webkitSpeechRecognition:
          webkit as unknown as SpeechRecognitionConstructor,
      }),
    ).toBe(standard);
    expect(
      getSpeechRecognitionConstructor({
        webkitSpeechRecognition:
          webkit as unknown as SpeechRecognitionConstructor,
      }),
    ).toBe(webkit);
    expect(getSpeechRecognitionConstructor({})).toBeNull();
  });

  it("maps DeerFlow locales to browser recognition locales", () => {
    expect(getSpeechRecognitionLanguage("zh-CN")).toBe("zh-CN");
    expect(getSpeechRecognitionLanguage("zh-Hans")).toBe("zh-CN");
    expect(getSpeechRecognitionLanguage("en-US")).toBe("en-US");
    expect(getSpeechRecognitionLanguage("en-GB")).toBe("en-GB");
    expect(getSpeechRecognitionLanguage("fr-FR")).toBe("fr-FR");
    expect(getSpeechRecognitionLanguage("ja-JP")).toBe("ja-JP");
    expect(getSpeechRecognitionLanguage("xx-YY")).toBe("en-US");
    expect(getSpeechRecognitionLanguage("not a locale")).toBe("en-US");
  });

  it("combines final and interim transcripts with whitespace cleanup", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 3,
        0: { isFinal: true, length: 1, 0: { transcript: " hello " } },
        1: { isFinal: true, length: 1, 0: { transcript: " world" } },
        2: { isFinal: false, length: 1, 0: { transcript: " again  " } },
      }),
    ).toEqual({
      finalText: "hello world",
      interimText: "again",
      text: "hello world again",
    });
  });

  it("appends transcript to an existing draft without duplicating whitespace", () => {
    expect(appendSpeechTranscript("", "  hello  world ")).toBe("hello world");
    expect(appendSpeechTranscript("Draft", "voice text")).toBe(
      "Draft voice text",
    );
    expect(appendSpeechTranscript("Draft\n", "voice text")).toBe(
      "Draft voice text",
    );
    expect(appendSpeechTranscript("Draft", "   ")).toBe("Draft");
  });

  it("normalizes browser speech recognition errors", () => {
    expect(mapSpeechRecognitionError("not-allowed")).toBe("permission_denied");
    expect(mapSpeechRecognitionError("service-not-allowed")).toBe(
      "permission_denied",
    );
    expect(mapSpeechRecognitionError("audio-capture")).toBe(
      "microphone_unavailable",
    );
    expect(mapSpeechRecognitionError("language-not-supported")).toBe(
      "unsupported_language",
    );
    expect(mapSpeechRecognitionError("network")).toBe("network");
    expect(mapSpeechRecognitionError("no-speech")).toBe("no_speech");
    expect(mapSpeechRecognitionError("aborted")).toBe("cancelled");
    expect(mapSpeechRecognitionError("bad-grammar")).toBe("unknown");
  });

  it("restarts only after browser auto-end conditions", () => {
    expect(shouldRestartSpeechRecognition(null)).toBe(true);
    expect(shouldRestartSpeechRecognition("no_speech")).toBe(true);
    expect(shouldRestartSpeechRecognition("cancelled")).toBe(false);
    expect(shouldRestartSpeechRecognition("permission_denied")).toBe(false);
    expect(shouldRestartSpeechRecognition("network")).toBe(false);
    expect(shouldRestartSpeechRecognition("unknown")).toBe(false);
  });
});

function makeSpeechRecognitionConstructor(): SpeechRecognitionConstructor {
  return class {
    continuous = false;
    interimResults = false;
    lang = "";
    maxAlternatives = 1;
    onend = null;
    onerror = null;
    onresult = null;

    start() {
      return undefined;
    }

    stop() {
      return undefined;
    }

    abort() {
      return undefined;
    }
  };
}
