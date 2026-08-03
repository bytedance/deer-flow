import { afterEach, describe, expect, it, rs } from "@rstest/core";

import { observeRenderActivity } from "@/core/dom/render-activity";

class IntersectionObserverMock {
  static instances: IntersectionObserverMock[] = [];

  callback: IntersectionObserverCallback;
  disconnect = rs.fn();
  observe = rs.fn();

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    IntersectionObserverMock.instances.push(this);
  }

  emit(isIntersecting: boolean) {
    this.callback(
      [{ isIntersecting } as IntersectionObserverEntry],
      this as never,
    );
  }
}

class MediaQueryListMock {
  matches = false;
  addEventListener = rs.fn();
  removeEventListener = rs.fn();
  private listener?: (event: MediaQueryListEvent) => void;

  constructor() {
    this.addEventListener.mockImplementation(
      (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        this.listener = listener;
      },
    );
  }

  emit(matches: boolean) {
    this.matches = matches;
    this.listener?.({ matches } as MediaQueryListEvent);
  }
}

describe("observeRenderActivity", () => {
  afterEach(() => {
    IntersectionObserverMock.instances = [];
    rs.restoreAllMocks();
    rs.unstubAllGlobals();
  });

  it("pauses for hidden documents and offscreen elements, then cleans up", () => {
    rs.stubGlobal("IntersectionObserver", IntersectionObserverMock);
    let hidden = false;
    rs.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    const removeEventListener = rs.spyOn(document, "removeEventListener");
    const states: boolean[] = [];

    const cleanup = observeRenderActivity(
      document.createElement("div"),
      (active) => {
        states.push(active);
      },
    );
    const observer = IntersectionObserverMock.instances[0]!;

    expect(states).toEqual([true]);
    observer.emit(false);
    expect(states).toEqual([true, false]);

    observer.emit(true);
    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(states).toEqual([true, false, true, false]);

    hidden = false;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(states.at(-1)).toBe(true);

    cleanup();
    expect(observer.disconnect).toHaveBeenCalledOnce();
    expect(removeEventListener).toHaveBeenCalledWith(
      "visibilitychange",
      expect.any(Function),
    );
  });

  it("pauses animations while reduced motion is requested", () => {
    const mediaQuery = new MediaQueryListMock();
    rs.stubGlobal(
      "matchMedia",
      rs.fn(() => mediaQuery),
    );
    const states: boolean[] = [];

    const cleanup = observeRenderActivity(
      document.createElement("div"),
      (active) => states.push(active),
    );

    expect(matchMedia).toHaveBeenCalledWith("(prefers-reduced-motion: reduce)");
    expect(states).toEqual([true]);

    mediaQuery.emit(true);
    expect(states).toEqual([true, false]);

    mediaQuery.emit(false);
    expect(states).toEqual([true, false, true]);

    cleanup();
    expect(mediaQuery.removeEventListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function),
    );
  });

  it("can preserve visible content while reduced motion is requested", () => {
    const mediaQuery = new MediaQueryListMock();
    mediaQuery.matches = true;
    rs.stubGlobal(
      "matchMedia",
      rs.fn(() => mediaQuery),
    );
    const states: boolean[] = [];

    const cleanup = observeRenderActivity(
      document.createElement("div"),
      (active) => states.push(active),
      true,
      false,
    );

    expect(states).toEqual([true]);
    expect(matchMedia).not.toHaveBeenCalled();
    cleanup();
  });
});
