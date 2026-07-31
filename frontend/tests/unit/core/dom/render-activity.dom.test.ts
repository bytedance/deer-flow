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
});
