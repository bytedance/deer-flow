import { describe, expect, test } from "vitest";

import {
  getAvailableInputSources,
  getInputSourceLabel,
  getInputSourcePlaceholder,
  getSafeInputSource,
  type InputSource,
} from "@/components/workspace/input-box";

describe("input box audio helpers", () => {
  const labels = {
    text: "Text input",
    microphone: "Microphone input",
    "audio-file": "Audio file input",
  } satisfies Record<InputSource, string>;

  test("returns the current input source label", () => {
    expect(getInputSourceLabel("text", labels)).toBe("Text input");
    expect(getInputSourceLabel("microphone", labels)).toBe("Microphone input");
    expect(getInputSourceLabel("audio-file", labels)).toBe("Audio file input");
  });

  test("uses the default placeholder for text input", () => {
    expect(
      getInputSourcePlaceholder({
        inputSource: "text",
        defaultPlaceholder: "How can I assist you today?",
        microphonePlaceholder: "Start speaking...",
        audioFilePlaceholder: "Choose an audio file...",
        microphoneUnsupportedPlaceholder: "Browser unsupported",
        microphoneSupported: true,
      }),
    ).toBe("How can I assist you today?");
  });

  test("uses the microphone placeholder when microphone recording is supported", () => {
    expect(
      getInputSourcePlaceholder({
        inputSource: "microphone",
        defaultPlaceholder: "How can I assist you today?",
        microphonePlaceholder: "Start speaking...",
        audioFilePlaceholder: "Choose an audio file...",
        microphoneUnsupportedPlaceholder: "Browser unsupported",
        microphoneSupported: true,
      }),
    ).toBe("Start speaking...");
  });

  test("falls back to the unsupported placeholder when microphone recording is unavailable", () => {
    expect(
      getInputSourcePlaceholder({
        inputSource: "microphone",
        defaultPlaceholder: "How can I assist you today?",
        microphonePlaceholder: "Start speaking...",
        audioFilePlaceholder: "Choose an audio file...",
        microphoneUnsupportedPlaceholder: "Browser unsupported",
        microphoneSupported: false,
      }),
    ).toBe("Browser unsupported");
  });

  test("uses the audio file placeholder for audio-file input", () => {
    expect(
      getInputSourcePlaceholder({
        inputSource: "audio-file",
        defaultPlaceholder: "How can I assist you today?",
        microphonePlaceholder: "Start speaking...",
        audioFilePlaceholder: "Choose an audio file...",
        microphoneUnsupportedPlaceholder: "Browser unsupported",
        microphoneSupported: true,
      }),
    ).toBe("Choose an audio file...");
  });

  test("derives available input sources from backend capabilities", () => {
    expect(
      getAvailableInputSources({
        enabled: true,
        microphone_enabled: true,
        file_transcription_enabled: false,
        default_locale: "zh-CN",
        supported_locales: ["zh-CN", "en-US"],
      }),
    ).toEqual(["text", "microphone"]);

    expect(
      getAvailableInputSources({
        enabled: true,
        microphone_enabled: false,
        file_transcription_enabled: true,
        default_locale: "zh-CN",
        supported_locales: ["zh-CN", "en-US"],
      }),
    ).toEqual(["text", "audio-file"]);

    expect(getAvailableInputSources()).toEqual(["text"]);
  });

  test("falls back to the first available source when the current source is unavailable", () => {
    expect(getSafeInputSource("microphone", ["text", "audio-file"])).toBe(
      "text",
    );
    expect(getSafeInputSource("audio-file", ["text", "audio-file"])).toBe(
      "audio-file",
    );
  });
});
