import { afterEach, expect, rs, test } from "@rstest/core";

rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
import { appendVoiceTranscript, transcribeAudio } from "@/core/voice-input/api";

afterEach(() => {
  rs.unstubAllGlobals();
});

test("keeps the draft when the transcript is empty and preserves transcript line breaks", () => {
  expect(appendVoiceTranscript("Draft  ", " ")).toBe("Draft  ");
  expect(appendVoiceTranscript("Task: ", " first\nsecond ")).toBe(
    "Task: first\nsecond",
  );
  expect(appendVoiceTranscript("", " 转写文本 ")).toBe("转写文本");
});

test("sends the encoded blob with session credentials and caller cancellation", async () => {
  const fetcher = rs
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ text: " hello " })));
  rs.stubGlobal("fetch", fetcher);
  const blob = new Blob(["audio"], { type: "audio/webm" });
  const signal = new AbortController().signal;
  expect(await transcribeAudio(blob, signal)).toBe("hello");
  expect(fetcher).toHaveBeenCalledWith(
    "/api/voice-input/transcribe",
    expect.objectContaining({
      method: "POST",
      body: blob,
      signal,
      credentials: "include",
    }),
  );
});

for (const [status, code] of [
  [404, "unavailable"],
  [413, "too_large"],
  [422, "no_speech"],
  [502, "failed"],
] as const) {
  test(`maps HTTP ${status} to safe UI error`, async () => {
    rs.stubGlobal(
      "fetch",
      rs.fn().mockResolvedValue(new Response("provider details", { status })),
    );
    await expect(
      transcribeAudio(new Blob(), new AbortController().signal),
    ).rejects.toMatchObject({ code });
  });
}
