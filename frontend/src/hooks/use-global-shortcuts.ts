"use client";

import { useEffect } from "react";

import { isDesktop } from "../lib/is-desktop.js";
import { openNewChatWindow } from "../lib/tauri.js";

export type ShortcutAction = () => void;

type OpenNewChatWindow = typeof openNewChatWindow;

export interface Shortcut {
  key: string;
  meta: boolean;
  shift?: boolean;
  action: ShortcutAction;
}

type ExecuteGlobalShortcutActionOptions = {
  isDesktop?: () => boolean;
  openNewChatWindow?: OpenNewChatWindow;
};

function isNewChatShortcut(shortcut: Shortcut): boolean {
  return (
    shortcut.meta &&
    (shortcut.shift ?? false) &&
    shortcut.key.toLowerCase() === "n"
  );
}

export function executeGlobalShortcutAction(
  shortcut: Shortcut,
  options: ExecuteGlobalShortcutActionOptions = {},
): void | Promise<string | undefined> {
  const detectDesktop = options.isDesktop ?? isDesktop;

  if (detectDesktop() && isNewChatShortcut(shortcut)) {
    return (options.openNewChatWindow ?? openNewChatWindow)();
  }

  shortcut.action();
  return undefined;
}

/**
 * Register global keyboard shortcuts on window.
 * Shortcuts are suppressed when focus is inside an input, textarea, or
 * contentEditable element - except for Cmd+K which always fires.
 */
export function useGlobalShortcuts(shortcuts: Shortcut[]) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const meta = event.metaKey || event.ctrlKey;

      for (const shortcut of shortcuts) {
        if (
          event.key.toLowerCase() === shortcut.key.toLowerCase() &&
          meta === shortcut.meta &&
          (shortcut.shift ?? false) === event.shiftKey
        ) {
          // Allow Cmd+K even in inputs (standard command palette behavior)
          if (shortcut.key !== "k") {
            const target = event.target as HTMLElement;
            const tag = target.tagName;
            if (
              tag === "INPUT" ||
              tag === "TEXTAREA" ||
              target.isContentEditable
            ) {
              continue;
            }
          }

          event.preventDefault();
          shortcut.action();
          return;
        }
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [shortcuts]);
}
