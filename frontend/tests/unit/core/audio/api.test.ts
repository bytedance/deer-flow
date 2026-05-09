import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { loadAudioInputConfig, transcribeAudio } from "@/core/audio/api";

function mockResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
  };
}

describe("audio api", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("transcribeAudio posts multipart form data to the thread endpoint", async () => {
    fetchMock.mockResolvedValue(
      mockResponse({
        success: true,
        transcript: "Hello from audio",
        language: "en-US",
        duration_ms: 1200,
        file: {
          filename: "meeting.webm",
          virtual_path: "/mnt/user-data/uploads/meeting.webm",
          artifact_url: "/api/threads/thread-123/artifacts/meeting.webm",
        },
      }),
    );

    const file = new File(["audio-bytes"], "meeting.webm", {
      type: "audio/webm",
    });

    await transcribeAudio("thread-123", file, {
      locale: "en-US",
      attachOriginal: true,
    });

    const [url, init] = fetchMock.mock.calls[0]!;
    const body = init.body as FormData;

    expect(url).toContain("/api/threads/thread-123/audio/transcriptions");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("file")).toBe(file);
    expect(body.get("locale")).toBe("en-US");
    expect(body.get("attach_original")).toBe("true");
  });

  test("loadAudioInputConfig returns the public audio capabilities", async () => {
    const payload = {
      enabled: true,
      microphone_enabled: true,
      file_transcription_enabled: true,
      default_locale: "zh-CN",
      supported_locales: ["zh-CN", "en-US"],
      accepted_mime_types: ["audio/webm", "audio/mpeg"],
      max_file_size: 26214400,
    };
    fetchMock.mockResolvedValue(mockResponse(payload));

    const result = await loadAudioInputConfig();

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/audio/config");
    expect(result).toEqual(payload);
  });

  test("transcribeAudio returns the parsed transcription payload", async () => {
    const payload = {
      success: true,
      transcript: "Ni hao",
      language: "zh-CN",
      duration_ms: 3456,
      file: {
        filename: "voice.m4a",
        virtual_path: "/mnt/user-data/uploads/voice.m4a",
        artifact_url: "/api/threads/thread-123/artifacts/voice.m4a",
      },
    };
    fetchMock.mockResolvedValue(mockResponse(payload));

    const result = await transcribeAudio(
      "thread-123",
      new File(["audio"], "voice.m4a", { type: "audio/mp4" }),
    );

    expect(result).toEqual(payload);
  });

  test("transcribeAudio throws backend detail when the request fails", async () => {
    fetchMock.mockResolvedValue(
      mockResponse({ detail: "Unsupported audio format" }, 415),
    );

    await expect(
      transcribeAudio(
        "thread-123",
        new File(["audio"], "voice.txt", { type: "text/plain" }),
      ),
    ).rejects.toThrow("Unsupported audio format");
  });

  test("transcribeAudio falls back to a generic error message when detail is unavailable", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: () => Promise.reject(new Error("parse error")),
    });

    await expect(
      transcribeAudio(
        "thread-123",
        new File(["audio"], "voice.m4a", { type: "audio/mp4" }),
      ),
    ).rejects.toThrow("Transcription failed");
  });
});
