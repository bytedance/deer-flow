import type { KeyboardEvent } from "react";

type IMEKeyboardEvent = KeyboardEvent<HTMLElement>;

export function isIMEComposing(
  event: IMEKeyboardEvent,
  isComposing = false,
): boolean {
  return isComposing || event.nativeEvent.isComposing || event.keyCode === 229;
}
