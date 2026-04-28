import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { getNovelCard } from "@/core/api/sessions";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MonitorConfig {
  idleTimeoutMinutes: number; // default 10
}

export interface MonitorState {
  enabled: boolean;
  config: MonitorConfig;
  dialogOpen: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHECK_INTERVAL_MS = 30_000; // 30 seconds
const MAX_STOP_WINDOW_MS = 2 * 60 * 1000; // 2 minutes
const STOP_COUNT_THRESHOLD = 3; // 3 consecutive fast stops
const PAUSE_RETRY_MS = 10 * 60 * 1000; // 10 minutes
const MAX_RETRY_ROUNDS = 1; // 1 retry round then permanent stop

// ---------------------------------------------------------------------------
// Build resume prompt
// ---------------------------------------------------------------------------

function buildResumePrompt(
  currentChapter: number,
  targetChapters: number,
): string {
  return (
    `<system_notification>\n` +
    `当前是自动续传任务，触发条件：card.json 中 target_chapters（${targetChapters}）> current_chapter（${currentChapter}）。\n\n` +
    `请继续写第${currentChapter + 1}章，一直写到第${targetChapters}章。\n\n` +
    `⚠️ 重要：每完成一章后，请立即更新 card.json 中的 current_chapter 数值。\n` +
    `   - 写完第 N 章后，将 current_chapter 设为 N\n` +
    `   - 当 current_chapter >= target_chapters 时，表示全部完成，监控将自动停止\n` +
    `</system_notification>`
  );
}

// ---------------------------------------------------------------------------
// Per-thread runtime stored outside React state so the interval callback
// always reads the freshest values without stale closures.
// ---------------------------------------------------------------------------

interface ThreadRuntime {
  enabled: boolean;
  config: MonitorConfig;
  stopTimes: number[]; // timestamps of each resume→stop transition
  errorStage: "idle" | "paused" | "stopped";
  retryRound: number;
  timerId: ReturnType<typeof setInterval> | null;
  retryTimerId: ReturnType<typeof setTimeout> | null;
  // refs supplied by the caller
  getIsLoading: () => boolean;
  getLastActivity: () => number;
  setLastActivity: (ts: number) => void;
  doSendMessage: (msg: string) => Promise<void>;
}

const runtimes = new Map<string, ThreadRuntime>();

function getRuntime(threadId: string): ThreadRuntime {
  let rt = runtimes.get(threadId);
  if (!rt) {
    rt = {
      enabled: false,
      config: { idleTimeoutMinutes: 10 },
      stopTimes: [],
      errorStage: "idle",
      retryRound: 0,
      timerId: null,
      retryTimerId: null,
      getIsLoading: () => false,
      getLastActivity: () => Date.now(),
      setLastActivity: () => {},
      doSendMessage: async () => {},
    };
    runtimes.set(threadId, rt);
  }
  return rt;
}

// ---------------------------------------------------------------------------
// Core monitoring loop
// ---------------------------------------------------------------------------

async function checkAndMaybeResume(rt: ThreadRuntime, threadId: string) {
  if (!rt.enabled || rt.errorStage === "stopped") return;

  // 1. Is the agent idle?
  if (rt.getIsLoading()) return;

  // 2. Has idle threshold been met?
  const idleMs = Date.now() - rt.getLastActivity();
  const thresholdMs = rt.config.idleTimeoutMinutes * 60 * 1000;
  if (idleMs < thresholdMs) return;

  // 3. Read card.json
  let card: { current_chapter: number; target_chapters: number };
  try {
    card = await getNovelCard(threadId);
  } catch {
    // read failure → don't break monitoring
    return;
  }

  // 4. Should we resume?
  if (card.target_chapters <= card.current_chapter) return;

  // 5. Send resume message
  const prompt = buildResumePrompt(card.current_chapter, card.target_chapters);
  try {
    await rt.doSendMessage(prompt);
  } catch {
    // send failure → treat as a stop
    rt.stopTimes.push(Date.now());
    maybeHandleErrorPattern(rt, threadId);
    return;
  }

  // Record that we just sent a message; the stop time will be recorded
  // when isLoading flips from true→false by the useEffect in the hook.
}

function maybeHandleErrorPattern(rt: ThreadRuntime, threadId: string) {
  const now = Date.now();
  const recent = rt.stopTimes.filter((t) => now - t <= MAX_STOP_WINDOW_MS * 2);
  rt.stopTimes = recent;

  if (recent.length >= STOP_COUNT_THRESHOLD) {
    const firstInWindow = recent[recent.length - STOP_COUNT_THRESHOLD];
    const lastInWindow = recent[recent.length - 1];
    if (lastInWindow - firstInWindow <= MAX_STOP_WINDOW_MS) {
      // Pattern detected: too many fast stops
      if (rt.retryRound < MAX_RETRY_ROUNDS) {
        // Pause and retry later
        rt.enabled = false;
        rt.errorStage = "paused";
        rt.retryRound += 1;
        if (rt.timerId) {
          clearInterval(rt.timerId);
          rt.timerId = null;
        }
        toast.warning(
          `LLM 接口持续报错，监控暂停，${PAUSE_RETRY_MS / 60000} 分钟后重试`,
        );
        rt.retryTimerId = setTimeout(() => {
          rt.enabled = true;
          rt.errorStage = "idle";
          rt.stopTimes = [];
          rt.retryTimerId = null;
          // restart timer
          rt.timerId = setInterval(
            () => void checkAndMaybeResume(rt, threadId),
            CHECK_INTERVAL_MS,
          );
        }, PAUSE_RETRY_MS);
      } else {
        // Permanent stop
        rt.enabled = false;
        rt.errorStage = "stopped";
        if (rt.timerId) {
          clearInterval(rt.timerId);
          rt.timerId = null;
        }
        toast.error("LLM 接口持续报错，监控已自动关闭");
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAutoResumeMonitor(
  threadId: string | undefined | null,
  getIsLoading: () => boolean,
  getLastActivity: () => number,
  setLastActivity: (ts: number) => void,
  doSendMessage: (msg: string) => Promise<void>,
) {
  const [monitorState, setMonitorState] = useState<MonitorState>({
    enabled: false,
    config: { idleTimeoutMinutes: 10 },
    dialogOpen: false,
  });

  const getIsLoadingRef = useRef(getIsLoading);
  const getLastActivityRef = useRef(getLastActivity);
  const setLastActivityRef = useRef(setLastActivity);
  const doSendMessageRef = useRef(doSendMessage);

  useEffect(() => {
    getIsLoadingRef.current = getIsLoading;
  }, [getIsLoading]);
  useEffect(() => {
    getLastActivityRef.current = getLastActivity;
  }, [getLastActivity]);
  useEffect(() => {
    setLastActivityRef.current = setLastActivity;
  }, [setLastActivity]);
  useEffect(() => {
    doSendMessageRef.current = doSendMessage;
  }, [doSendMessage]);

  // Register / unregister runtime
  useEffect(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    rt.getIsLoading = () => getIsLoadingRef.current();
    rt.getLastActivity = () => getLastActivityRef.current();
    rt.setLastActivity = (ts: number) => setLastActivityRef.current(ts);
    rt.doSendMessage = (msg: string) => doSendMessageRef.current(msg);
    return () => {
      if (rt.timerId) clearInterval(rt.timerId);
      if (rt.retryTimerId) clearTimeout(rt.retryTimerId);
      runtimes.delete(threadId);
    };
  }, [threadId]);

  // Sync React state → runtime
  useEffect(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    rt.enabled = monitorState.enabled;
    rt.config = monitorState.config;
  }, [threadId, monitorState]);

  // Track isLoading → stop transitions and record stop time
  const prevLoadingRef = useRef(false);
  useEffect(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    const isLoading = getIsLoadingRef.current();
    if (prevLoadingRef.current && !isLoading) {
      // transition: running → stopped
      rt.stopTimes.push(Date.now());
      // prune old entries
      const now = Date.now();
      rt.stopTimes = rt.stopTimes.filter(
        (t) => now - t <= MAX_STOP_WINDOW_MS * 2,
      );
      maybeHandleErrorPattern(rt, threadId);
    }
    prevLoadingRef.current = isLoading;
  }, [threadId, getIsLoading()]);

  // Update lastActivity when loading
  useEffect(() => {
    if (!threadId) return;
    if (getIsLoadingRef.current()) {
      setLastActivityRef.current(Date.now());
    }
  }, [threadId, getIsLoading()]);

  // -----------------------------------------------------------------------
  // Public actions
  // -----------------------------------------------------------------------

  const openDialog = useCallback(() => {
    setMonitorState((prev) => ({ ...prev, dialogOpen: true }));
  }, []);

  const closeDialog = useCallback(() => {
    setMonitorState((prev) => ({ ...prev, dialogOpen: false }));
  }, []);

  const updateConfig = useCallback((config: Partial<MonitorConfig>) => {
    setMonitorState((prev) => ({
      ...prev,
      config: { ...prev.config, ...config },
    }));
  }, []);

  const startMonitor = useCallback(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    rt.errorStage = "idle";
    rt.retryRound = 0;
    rt.stopTimes = [];

    setMonitorState((prev) => ({
      ...prev,
      enabled: true,
      dialogOpen: false,
    }));

    if (!rt.timerId) {
      rt.timerId = setInterval(
        () => void checkAndMaybeResume(rt, threadId),
        CHECK_INTERVAL_MS,
      );
    }

    toast.success("监控已启动");
  }, [threadId]);

  const stopMonitor = useCallback(
    (permanent = false) => {
      if (!threadId) return;
      const rt = getRuntime(threadId);
      if (rt.timerId) {
        clearInterval(rt.timerId);
        rt.timerId = null;
      }
      if (rt.retryTimerId) {
        clearTimeout(rt.retryTimerId);
        rt.retryTimerId = null;
      }
      rt.enabled = false;
      rt.errorStage = permanent ? "stopped" : "idle";
      rt.retryRound = 0;
      rt.stopTimes = [];

      setMonitorState((prev) => ({
        ...prev,
        enabled: false,
        dialogOpen: false,
      }));

      if (permanent) {
        toast.error("监控已自动关闭（LLM 接口持续报错）");
      } else {
        toast.info("监控已停止");
      }
    },
    [threadId],
  );

  // Also sync back when errorStage changes externally (pause/stop by timer)
  const [syncTick, setSyncTick] = useState(0);
  useEffect(() => {
    if (!threadId) return;
    const rt = getRuntime(threadId);
    if (
      !rt.enabled &&
      (rt.errorStage === "stopped" || rt.errorStage === "paused") &&
      monitorState.enabled
    ) {
      setMonitorState((prev) => ({ ...prev, enabled: false }));
    }
    // poll for external state changes every 5 s
    const id = setInterval(() => setSyncTick((t) => t + 1), 5000);
    return () => clearInterval(id);
  }, [threadId]);

  return {
    monitorState,
    openDialog,
    closeDialog,
    updateConfig,
    startMonitor,
    stopMonitor,
  };
}
