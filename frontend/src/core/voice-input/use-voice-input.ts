import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import {
  transcribeAudio,
  VoiceInputError,
  type VoiceInputErrorCode,
} from "./api";

export type VoiceInputPhase = "idle" | "starting" | "listening" | "stopping";
type Session = {
  controller: AbortController;
  stream?: MediaStream;
  recorder?: MediaRecorder;
  timer?: ReturnType<typeof setTimeout>;
  chunks: Blob[];
  bytes: number;
};

function recordingMimeType(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  return (
    ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find(
      (mime) => MediaRecorder.isTypeSupported(mime),
    ) ?? null
  );
}

function releaseMicrophone(session: Session) {
  session.stream?.getTracks().forEach((track) => track.stop());
  session.stream = undefined;
  clearTimeout(session.timer);
}

/** One recording and one transcription, owned by the current composer scope. */
export function useVoiceInput({
  enabled,
  scope,
  maxBytes,
  maxSeconds,
  onTranscript,
  onError,
}: {
  enabled: boolean;
  scope: string;
  maxBytes: number;
  maxSeconds: number;
  onTranscript: (text: string) => void;
  onError: (code: VoiceInputErrorCode) => void;
}) {
  const [phase, setPhase] = useState<VoiceInputPhase>("idle");
  const [supported, setSupported] = useState(false);
  const sessionRef = useRef<Session | null>(null);
  const callbacks = useRef({ onTranscript, onError });
  useLayoutEffect(() => {
    callbacks.current = { onTranscript, onError };
  }, [onTranscript, onError]);
  useEffect(() => {
    setSupported(
      window.isSecureContext &&
        !!navigator.mediaDevices?.getUserMedia &&
        recordingMimeType() !== null,
    );
  }, []);

  const abort = useCallback(() => {
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) {
      session.controller.abort();
      const recorder = session.recorder;
      if (recorder) {
        recorder.ondataavailable = null;
        recorder.onstop = null;
        recorder.onerror = null;
        if (recorder.state !== "inactive") {
          try {
            recorder.stop();
          } catch {
            /* Already stopped by the browser. */
          }
        }
      }
      releaseMicrophone(session);
      session.chunks = [];
    }
    setPhase("idle");
  }, []);

  useLayoutEffect(() => {
    if (!enabled) abort();
    return abort;
  }, [abort, enabled, scope]);

  const fail = useCallback(
    (session: Session, code: VoiceInputErrorCode) => {
      if (sessionRef.current !== session) return;
      abort();
      callbacks.current.onError(code);
    },
    [abort],
  );

  const stop = useCallback(() => {
    const session = sessionRef.current;
    if (!session) return;
    if (!session.recorder) {
      abort();
      return;
    }
    if (session.recorder.state === "inactive") return;
    setPhase("stopping");
    clearTimeout(session.timer);
    // A recorder that never dispatches stop must still release the device.
    session.timer = setTimeout(() => fail(session, "failed"), 5000);
    try {
      session.recorder.stop();
    } catch {
      fail(session, "failed");
    }
  }, [abort, fail]);

  const start = useCallback(async () => {
    if (!enabled || sessionRef.current) return;
    const mimeType = recordingMimeType();
    if (!supported || !mimeType) {
      callbacks.current.onError("unsupported");
      return;
    }
    const session: Session = {
      controller: new AbortController(),
      chunks: [],
      bytes: 0,
    };
    sessionRef.current = session;
    setPhase("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Permission can resolve after Cancel, navigation or account switching.
      if (sessionRef.current !== session) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      session.stream = stream;
      const recorder = new MediaRecorder(stream, {
        mimeType,
        audioBitsPerSecond: 64000,
      });
      session.recorder = recorder;
      recorder.ondataavailable = (event) => {
        if (sessionRef.current !== session || !event.data.size) return;
        session.bytes += event.data.size;
        if (session.bytes > maxBytes) {
          fail(session, "too_large");
          return;
        }
        session.chunks.push(event.data);
      };
      recorder.onerror = () => fail(session, "failed");
      recorder.onstop = () => {
        if (sessionRef.current !== session) return;
        releaseMicrophone(session);
        setPhase("stopping");
        const audio = new Blob(session.chunks, {
          type: recorder.mimeType || mimeType,
        });
        session.chunks = [];
        if (!audio.size) {
          fail(session, "no_speech");
          return;
        }
        // Bound the whole HTTP exchange as well as the backend's provider call.
        session.timer = setTimeout(() => fail(session, "failed"), 155000);
        void transcribeAudio(audio, session.controller.signal)
          .then((text) => {
            if (sessionRef.current !== session) return;
            abort();
            callbacks.current.onTranscript(text);
          })
          .catch((error: unknown) => {
            fail(
              session,
              error instanceof VoiceInputError ? error.code : "failed",
            );
          });
      };
      recorder.start(250);
      setPhase("listening");
      session.timer = setTimeout(stop, maxSeconds * 1000);
    } catch (error) {
      const name = error instanceof Error ? error.name : "";
      fail(
        session,
        name === "NotAllowedError"
          ? "permission_denied"
          : name === "NotFoundError" || name === "NotReadableError"
            ? "microphone_unavailable"
            : "failed",
      );
    }
  }, [abort, enabled, fail, maxBytes, maxSeconds, stop, supported]);

  return { phase, supported, start, stop, abort };
}
