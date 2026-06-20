import { afterEach, describe, expect, test, vi } from "vitest";

type KeydownHandler = (event: KeyboardEvent) => void;

async function loadHookWithCapturedHandler() {
  let cleanup: (() => void) | undefined;
  let keydownHandler: KeydownHandler | undefined;

  const addEventListener = vi.fn(
    (type: string, listener: EventListenerOrEventListenerObject) => {
      if (type === "keydown" && typeof listener === "function") {
        keydownHandler = listener as KeydownHandler;
      }
    },
  );
  const removeEventListener = vi.fn();

  vi.resetModules();
  vi.doMock("react", () => ({
    useEffect: (effect: () => void | (() => void)) => {
      const result = effect();
      cleanup = typeof result === "function" ? result : undefined;
    },
  }));
  vi.stubGlobal("window", { addEventListener, removeEventListener });

  const { useGlobalShortcuts } = await import("@/hooks/use-global-shortcuts");

  return {
    cleanup: () => cleanup?.(),
    getKeydownHandler: () => keydownHandler,
    useGlobalShortcuts,
  };
}

afterEach(() => {
  vi.doUnmock("react");
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("useGlobalShortcuts", () => {
  test("ignores keydown events without a key", async () => {
    const action = vi.fn();
    const { getKeydownHandler, useGlobalShortcuts } =
      await loadHookWithCapturedHandler();

    useGlobalShortcuts([{ key: "k", meta: true, action }]);

    const keydownHandler = getKeydownHandler();
    expect(keydownHandler).toBeDefined();
    expect(() =>
      keydownHandler?.({
        ctrlKey: false,
        metaKey: true,
        shiftKey: false,
      } as KeyboardEvent),
    ).not.toThrow();
    expect(action).not.toHaveBeenCalled();
  });
});
