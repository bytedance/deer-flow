import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

const api = rs.hoisted(() => ({ transcribeAudio: rs.fn() }));
rs.mock("@/core/voice-input/api", () => ({
  transcribeAudio: api.transcribeAudio,
  VoiceInputError: class extends Error {
    code = "failed";
  },
}));
import { useVoiceInput } from "@/core/voice-input/use-voice-input";

class Recorder {
  static current: Recorder;
  static isTypeSupported = () => true;
  state = "inactive";
  mimeType = "audio/webm";
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  constructor() {
    Recorder.current = this;
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"]) });
    this.onstop?.();
  }
}
const stopTrack = rs.fn();
const stream = {
  getTracks: () => [{ stop: stopTrack }],
} as unknown as MediaStream;
const getUserMedia = rs.fn<() => Promise<MediaStream>>();
const originalMedia = Object.getOwnPropertyDescriptor(
  navigator,
  "mediaDevices",
);
const originalSecure = Object.getOwnPropertyDescriptor(
  window,
  "isSecureContext",
);

beforeEach(() => {
  stopTrack.mockClear();
  getUserMedia.mockReset().mockResolvedValue(stream);
  api.transcribeAudio.mockReset().mockResolvedValue("spoken text");
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value: true,
  });
  rs.stubGlobal("MediaRecorder", Recorder);
});
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  if (originalMedia)
    Object.defineProperty(navigator, "mediaDevices", originalMedia);
  else Reflect.deleteProperty(navigator, "mediaDevices");
  if (originalSecure)
    Object.defineProperty(window, "isSecureContext", originalSecure);
  else Reflect.deleteProperty(window, "isSecureContext");
});
function setup(enabled = true) {
  const onTranscript = rs.fn();
  const onError = rs.fn();
  const hook = renderHook(
    ({ scope, available }) =>
      useVoiceInput({
        enabled: available,
        scope,
        maxBytes: 1024,
        maxSeconds: 120,
        onTranscript,
        onError,
      }),
    { initialProps: { scope: "thread-a", available: enabled } },
  );
  return { ...hook, onTranscript, onError };
}

test("unconfigured input never requests microphone access", async () => {
  const { result } = setup(false);
  await act(() => result.current.start());
  expect(getUserMedia).not.toHaveBeenCalled();
  expect(result.current.phase).toBe("idle");
});

test("permission denied permits retry and does not upload", async () => {
  getUserMedia.mockRejectedValueOnce(
    new DOMException("denied", "NotAllowedError"),
  );
  const { result, onError } = setup();
  await act(() => result.current.start());
  expect(onError).toHaveBeenCalledWith("permission_denied");
  expect(result.current.phase).toBe("idle");
  expect(api.transcribeAudio).not.toHaveBeenCalled();
  await act(() => result.current.start());
  expect(result.current.phase).toBe("listening");
});

test("cancel while permission is pending stops the late stream", async () => {
  let release!: (stream: MediaStream) => void;
  getUserMedia.mockReturnValue(
    new Promise((resolve) => {
      release = resolve;
    }),
  );
  const { result, onTranscript } = setup();
  let started!: Promise<void>;
  act(() => {
    started = result.current.start();
  });
  expect(result.current.phase).toBe("starting");
  act(() => result.current.abort());
  await act(async () => {
    release(stream);
    await started;
  });
  expect(stopTrack).toHaveBeenCalledTimes(1);
  expect(api.transcribeAudio).not.toHaveBeenCalled();
  expect(onTranscript).not.toHaveBeenCalled();
});

test("finishing uploads once and releases the microphone before STT completes", async () => {
  let finish!: (text: string) => void;
  api.transcribeAudio.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const { result, onTranscript } = setup();
  await act(() => result.current.start());
  act(() => {
    result.current.stop();
    result.current.stop();
  });
  expect(stopTrack).toHaveBeenCalledTimes(1);
  expect(api.transcribeAudio).toHaveBeenCalledTimes(1);
  expect(result.current.phase).toBe("stopping");
  expect(onTranscript).not.toHaveBeenCalled();
  await act(async () => {
    finish("final text");
  });
  expect(onTranscript).toHaveBeenCalledWith("final text");
  expect(result.current.phase).toBe("idle");
});

for (const boundary of ["cancel", "thread", "disable", "unmount"] as const) {
  test(`${boundary} aborts a pending upload and ignores its late response`, async () => {
    let finish!: (text: string) => void;
    api.transcribeAudio.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { result, rerender, unmount, onTranscript, onError } = setup();
    await act(() => result.current.start());
    act(() => result.current.stop());
    const signal = api.transcribeAudio.mock.calls[0]![1] as AbortSignal;
    if (boundary === "cancel") act(() => result.current.abort());
    if (boundary === "thread") rerender({ scope: "thread-b", available: true });
    if (boundary === "disable")
      rerender({ scope: "thread-a", available: false });
    if (boundary === "unmount") unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => {
      finish("stale text");
    });
    expect(onTranscript).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });
}

test("oversized recording aborts without sending audio", async () => {
  const { result, onError } = setup();
  await act(() => result.current.start());
  act(() =>
    Recorder.current.ondataavailable?.({ data: new Blob(["a".repeat(1025)]) }),
  );
  expect(onError).toHaveBeenCalledWith("too_large");
  expect(stopTrack).toHaveBeenCalledTimes(1);
  expect(api.transcribeAudio).not.toHaveBeenCalled();
  expect(result.current.phase).toBe("idle");
});
