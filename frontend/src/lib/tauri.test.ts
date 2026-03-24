import assert from "node:assert/strict";
import test from "node:test";

import type { LoadTauriCore } from "./tauri";

type IsDesktopModule = {
  isDesktop: () => boolean;
};

type TauriModule = {
  openNewChatWindow: (options?: {
    isDesktop?: () => boolean;
    loadCore?: LoadTauriCore;
  }) => Promise<string | undefined>;
  openThreadInNewWindow: (
    threadId: string,
    options?: {
      isDesktop?: () => boolean;
      loadCore?: LoadTauriCore;
    },
  ) => Promise<string | undefined>;
};

const isDesktopModuleUrl = new URL("./is-desktop.ts", import.meta.url).href;
const { isDesktop } = (await import(isDesktopModuleUrl)) as IsDesktopModule;

const tauriModuleUrl = new URL("./tauri.ts", import.meta.url).href;
const { openNewChatWindow, openThreadInNewWindow } = (await import(
  tauriModuleUrl,
)) as TauriModule;

void test("isDesktop returns false when the Tauri runtime is unavailable", () => {
  assert.equal(isDesktop(), false);
});

void test("openNewChatWindow is a safe no-op outside desktop mode", async () => {
  let loadAttempts = 0;

  const loadCore: LoadTauriCore = async () => {
    loadAttempts += 1;

    return {
      invoke: async <T>() => "chat-new-1" as T,
    };
  };

  const result = await openNewChatWindow({
    isDesktop: () => false,
    loadCore,
  });

  assert.equal(result, undefined);
  assert.equal(loadAttempts, 0);
});

void test(
  "openThreadInNewWindow reaches the Tauri loader path in desktop mode",
  async () => {
    let loadAttempts = 0;
    let invokedCommand = "";
    let invokedArgs: unknown;

    const loadCore: LoadTauriCore = async () => {
      loadAttempts += 1;

      return {
        invoke: async <T>(command: string, args?: Record<string, unknown>) => {
          invokedCommand = command;
          invokedArgs = args;

          return "chat-thread-thread-123-1" as T;
        },
      };
    };

    const result = await openThreadInNewWindow("thread-123", {
      isDesktop: () => true,
      loadCore,
    });

    assert.equal(result, "chat-thread-thread-123-1");
    assert.equal(loadAttempts, 1);
    assert.equal(invokedCommand, "open_thread_window");
    assert.deepEqual(invokedArgs, { threadId: "thread-123" });
  },
);
