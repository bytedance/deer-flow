import { afterEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

import { useIsMobile } from "@/hooks/use-mobile";

type HappyDOMWindow = typeof window & {
  happyDOM: { setViewport: (viewport: { width?: number }) => void };
};

function setViewportWidth(width: number) {
  (window as HappyDOMWindow).happyDOM.setViewport({ width });
}

afterEach(() => {
  cleanup();
  setViewportWidth(1024);
});

describe("useIsMobile", () => {
  it("reports the viewport it mounted into", () => {
    setViewportWidth(1024);
    expect(renderHook(() => useIsMobile()).result.current).toBe(false);
    cleanup();

    setViewportWidth(500);
    expect(renderHook(() => useIsMobile()).result.current).toBe(true);
  });

  it("re-renders when the viewport crosses the breakpoint", () => {
    setViewportWidth(1024);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    act(() => setViewportWidth(500));
    expect(result.current).toBe(true);

    act(() => setViewportWidth(1024));
    expect(result.current).toBe(false);
  });

  it("switches at 768px", () => {
    setViewportWidth(767);
    expect(renderHook(() => useIsMobile()).result.current).toBe(true);
    cleanup();

    setViewportWidth(768);
    expect(renderHook(() => useIsMobile()).result.current).toBe(false);
  });

  it("drops its media-query listener on unmount", () => {
    // The subscribe callback creates its own MediaQueryList, so the only way to
    // observe the leak is to count through the factory it calls.
    const nativeMatchMedia = window.matchMedia.bind(window);
    let added = 0;
    let removed = 0;
    window.matchMedia = (query: string) => {
      const mql = nativeMatchMedia(query);
      const nativeAdd = mql.addEventListener.bind(mql);
      const nativeRemove = mql.removeEventListener.bind(mql);
      mql.addEventListener = ((...args: Parameters<typeof nativeAdd>) => {
        added += 1;
        return nativeAdd(...args);
      }) as typeof mql.addEventListener;
      mql.removeEventListener = ((...args: Parameters<typeof nativeRemove>) => {
        removed += 1;
        return nativeRemove(...args);
      }) as typeof mql.removeEventListener;
      return mql;
    };

    try {
      const { unmount } = renderHook(() => useIsMobile());
      expect(added).toBeGreaterThan(0);
      expect(removed).toBe(0);

      unmount();
      expect(removed).toBe(added);
    } finally {
      window.matchMedia = nativeMatchMedia;
    }
  });
});
