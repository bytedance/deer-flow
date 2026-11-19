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

  it("separates unpadded final and interim segments", () => {
    // WebKit-style providers trim final transcripts; without an explicit
    // separator the finalized text glues onto the interim hypothesis.
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: "hello world" } },
        1: { isFinal: false, length: 1, 0: { transcript: "today is" } },
      }),
    ).toEqual({
      finalText: "hello world",
      interimText: "today is",
      text: "hello world today is",
    });
  });

  it("separates consecutive unpadded final segments", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: "hello" } },
        1: { isFinal: true, length: 1, 0: { transcript: "world" } },
      }),
    ).toEqual({
      finalText: "hello world",
      interimText: "",
      text: "hello world",
    });
  });

  it("adds no separator when the provider already emitted boundary space", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: "hello world " } },
        1: { isFinal: false, length: 1, 0: { transcript: "today" } },
      }).text,
    ).toBe("hello world today");
  });

  it("keeps CJK segments glued when the provider emits no spaces", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: "你好世界" } },
        1: { isFinal: false, length: 1, 0: { transcript: "今天" } },
      }).text,
    ).toBe("你好世界今天");
  });

  it("separates consecutive trimmed finals accumulated over a session", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 3,
        0: { isFinal: true, length: 1, 0: { transcript: "hello" } },
        1: { isFinal: true, length: 1, 0: { transcript: "world" } },
        2: { isFinal: false, length: 1, 0: { transcript: "today" } },
      }),
    ).toEqual({
      finalText: "hello world",
      interimText: "today",
      text: "hello world today",
    });
  });

  it.each(["cet été", "cafe\u0301"])(
    "separates accented Latin words after %s",
    (finalText) => {
      expect(
        readSpeechRecognitionTranscript({
          length: 2,
          0: { isFinal: true, length: 1, 0: { transcript: finalText } },
          1: { isFinal: false, length: 1, 0: { transcript: "demain" } },
        }).text,
      ).toBe(`${finalText} demain`);
    },
  );

  it("keeps digit and symbol boundaries glued", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: "up to 50" } },
        1: { isFinal: false, length: 1, 0: { transcript: "%" } },
      }).text,
    ).toBe("up to 50%");
  });

  it("attaches leading punctuation across final and interim segments", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 4,
        0: { isFinal: true, length: 1, 0: { transcript: "done" } },
        1: { isFinal: true, length: 1, 0: { transcript: ", maybe" } },
        2: { isFinal: false, length: 1, 0: { transcript: "next" } },
        3: { isFinal: false, length: 1, 0: { transcript: ", please" } },
      }),
    ).toEqual({
      finalText: "done, maybe",
      interimText: "next, please",
      text: "done, maybe next, please",
    });
  });

  it.each([
    ["Done.", "Next", "Done. Next"],
    ["Hello,", "world", "Hello, world"],
    ["she said", '"hello"', 'she said "hello"'],
    ['"hello"', "again", '"hello" again'],
  ])("separates phrases at %s / %s", (left, right, text) => {
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: left } },
        1: { isFinal: false, length: 1, 0: { transcript: right } },
      }).text,
    ).toBe(text);
  });

  it("preserves separation across whitespace-only final segments", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 3,
        0: { isFinal: true, length: 1, 0: { transcript: "hello" } },
        1: { isFinal: true, length: 1, 0: { transcript: " " } },
        2: { isFinal: true, length: 1, 0: { transcript: "world" } },
      }),
    ).toEqual({
      finalText: "hello world",
      interimText: "",
      text: "hello world",
    });
  });

  it("keeps no-space scripts concatenated without inserting separators", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 3,
        0: { isFinal: true, length: 1, 0: { transcript: "你好" } },
        1: { isFinal: true, length: 1, 0: { transcript: "世界" } },
        2: { isFinal: false, length: 1, 0: { transcript: "早上好" } },
      }),
    ).toEqual({
      finalText: "你好世界",
      interimText: "早上好",
      text: "你好世界早上好",
    });
  });

  it("keeps mixed-script boundaries concatenated", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: "你好" } },
        1: { isFinal: false, length: 1, 0: { transcript: "hello" } },
      }),
    ).toEqual({
      finalText: "你好",
      interimText: "hello",
      text: "你好hello",
    });
  });

  it("keeps CJK clause-final punctuation boundaries concatenated", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: "こんにちは、" } },
        1: { isFinal: false, length: 1, 0: { transcript: "iPhone" } },
      }),
    ).toEqual({
      finalText: "こんにちは、",
      interimText: "iPhone",
      text: "こんにちは、iPhone",
    });
  });

  it("joins Korean segments with a space like other space-delimited scripts", () => {
    expect(
      readSpeechRecognitionTranscript({
        length: 2,
        0: { isFinal: true, length: 1, 0: { transcript: "안녕" } },
        1: { isFinal: false, length: 1, 0: { transcript: "하세요" } },
      }),
    ).toEqual({
      finalText: "안녕",
      interimText: "하세요",
      text: "안녕 하세요",
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
