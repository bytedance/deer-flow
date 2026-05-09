import { describe, expect, test } from "vitest";

import {
  getNextPendingAudioAttachment,
  isAudioPromptInputFile,
  resolveAudioLocale,
} from "@/components/workspace/input-box";

describe("input box audio file helpers", () => {
  test("identifies prompt input audio files by media type", () => {
    expect(
      isAudioPromptInputFile({
        mediaType: "audio/webm",
      }),
    ).toBe(true);

    expect(
      isAudioPromptInputFile({
        mediaType: "text/plain",
      }),
    ).toBe(false);
  });

  test("returns the next unattached audio file candidate", () => {
    const audioCandidate = {
      id: "audio-1",
      mediaType: "audio/mpeg",
      filename: "voice.mp3",
      type: "file" as const,
      url: "blob:voice",
    };

    const files = [
      {
        id: "text-1",
        mediaType: "text/plain",
        filename: "notes.txt",
        type: "file" as const,
        url: "blob:notes",
      },
      audioCandidate,
      {
        id: "audio-2",
        mediaType: "audio/webm",
        filename: "meeting.webm",
        type: "file" as const,
        url: "blob:meeting",
      },
    ];

    expect(getNextPendingAudioAttachment(files, new Set())).toEqual(
      audioCandidate,
    );
    expect(
      getNextPendingAudioAttachment(files, new Set(["audio-1"])),
    ).toEqual(files[2]);
    expect(
      getNextPendingAudioAttachment(files, new Set(["audio-1", "audio-2"])),
    ).toBeUndefined();
  });

  test("normalizes browser locales to the supported transcription locales", () => {
    expect(resolveAudioLocale("zh", ["zh-CN", "en-US"], "en-US")).toBe(
      "zh-CN",
    );
    expect(resolveAudioLocale("zh-TW", ["zh-CN", "en-US"], "en-US")).toBe(
      "zh-CN",
    );
    expect(resolveAudioLocale("en-GB", ["zh-CN", "en-US"], "zh-CN")).toBe(
      "en-US",
    );
    expect(resolveAudioLocale("fr-FR", ["zh-CN", "en-US"], "zh-CN")).toBe(
      "zh-CN",
    );
    expect(resolveAudioLocale(undefined, ["zh-CN", "en-US"], "en-US")).toBe(
      "en-US",
    );
  });
});
