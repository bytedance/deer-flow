"use client";

import * as React from "react";

/**
 * Track the visual-viewport occlusion caused by the on-screen keyboard.
 *
 * The browser platform has two partial solutions for this problem:
 *
 * - ``env(keyboard-inset-*)`` — populated by the VirtualKeyboard API on
 *   Chromium 94+. Zero on Safari iOS, which has not shipped that API.
 * - ``interactive-widget=resizes-content`` viewport meta — honoured by
 *   Chromium 108+ but ignored by Safari iOS (WebKit bug 242356).
 *
 * Neither covers iPhone Safari. The only cross-browser source is the
 * ``window.visualViewport`` object: its ``height`` shrinks when the
 * keyboard opens, and the difference to the layout viewport is the
 * keyboard inset.
 *
 * This hook tracks that difference and mirrors it to the CSS custom
 * property ``--keyboard-inset-js`` on the ``<html>`` element, so CSS can
 * compose a cross-browser inset via ``max(env(keyboard-inset-bottom),
 * var(--keyboard-inset-js, 0px))`` without needing React state on every
 * consumer.
 *
 * Returns the current inset in pixels so individual components can also
 * react directly (e.g. to scroll into view when focus lands on an
 * element behind the keyboard).
 */
export function useVisualViewport(): number {
  const [keyboardInset, setKeyboardInset] = React.useState(0);

  React.useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) {
      // Very old browsers have no visualViewport object at all. In that
      // case the keyboard overlaps content — there is nothing we can do
      // in JS; the safe-area / env() fallbacks still apply.
      return;
    }

    const root = document.documentElement;
    const apply = () => {
      // innerHeight reflects the layout viewport; visualViewport.height
      // reflects the visible area after the keyboard pushes up. The
      // difference is the keyboard's CSS height. ``offsetTop`` accounts
      // for cases where the visual viewport shifts rather than shrinks
      // (happens on some iOS versions).
      const inset = Math.max(
        0,
        window.innerHeight - vv.height - vv.offsetTop,
      );
      setKeyboardInset(inset);
      root.style.setProperty("--keyboard-inset-js", `${inset}px`);
    };

    apply();
    vv.addEventListener("resize", apply);
    vv.addEventListener("scroll", apply);
    return () => {
      vv.removeEventListener("resize", apply);
      vv.removeEventListener("scroll", apply);
      root.style.removeProperty("--keyboard-inset-js");
    };
  }, []);

  return keyboardInset;
}
