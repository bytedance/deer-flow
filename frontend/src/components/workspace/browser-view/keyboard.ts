import type { BrowserInputEvent } from "./use-browser-stream";

// Named keys we forward to the remote page as key presses (everything else that
// is a single printable char is forwarded as text). Chosen to cover editing and
// navigation without leaking browser-level shortcuts.
export const FORWARDED_NAMED_KEYS = [
  "Enter",
  "Backspace",
  "Tab",
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Escape",
  "Delete",
] as const;

export interface BrowserKeyContext {
  /** Panel is in Live (interactive) mode. */
  live: boolean;
  /** Focus is on an editable element (URL bar etc.) — keep it local. */
  editableTarget: boolean;
  /** An IME composition is active — the keystroke belongs to the composer. */
  composing: boolean;
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
}

/**
 * Decide how a keydown maps to a remote browser input, or ``null`` to ignore it.
 *
 * Pure so the forwarding policy (including the IME-composition guard that must
 * swallow a composing Enter) can be unit-tested without a DOM.
 */
export function decideBrowserKeyInput(
  ctx: BrowserKeyContext,
): BrowserInputEvent | null {
  if (!ctx.live || ctx.editableTarget || ctx.composing) {
    return null;
  }
  if ((ctx.ctrlKey || ctx.metaKey) && ctx.key.length === 1) {
    return {
      type: "key",
      key: `${ctx.metaKey ? "Meta" : "Control"}+${ctx.key.toUpperCase()}`,
    };
  }
  if (ctx.key.length === 1 && !ctx.metaKey && !ctx.ctrlKey) {
    return { type: "text", text: ctx.key };
  }
  if ((FORWARDED_NAMED_KEYS as readonly string[]).includes(ctx.key)) {
    return { type: "key", key: ctx.key };
  }
  return null;
}
