import { afterEach, describe, expect, test, rs } from "@rstest/core";

type KeydownHandler = (event: KeyboardEvent) => void;

async function loadHookWithCapturedHandler() {
  let cleanup: (() => void) | undefined;
  let keydownHandler: KeydownHandler | undefined;

  const addEventListener = rs.fn(
    (type: string, listener: EventListenerOrEventListenerObject) => {
      if (type === "keydown" && typeof listener === "function") {
        keydownHandler = listener as KeydownHandler;
      }
    },
  );
  const removeEventListener = rs.fn();

  rs.resetModules();
  rs.doMock("react", () => ({
    useEffect: (effect: () => void | (() => void)) => {
      const result = effect();
      cleanup = typeof result === "function" ? result : undefined;
    },
  }));
  rs.stubGlobal("window", { addEventListener, removeEventListener });

  const { useGlobalShortcuts } = await import("@/hooks/use-global-shortcuts");

  return {
    cleanup: () => cleanup?.(),
    getKeydownHandler: () => keydownHandler,
    useGlobalShortcuts,
  };
}

afterEach(() => {
  rs.doUnmock("react");
  rs.unstubAllGlobals();
  rs.resetModules();
});

describe("useGlobalShortcuts", () => {
  test("ignores keydown events without a key", async () => {
    const action = rs.fn();
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
