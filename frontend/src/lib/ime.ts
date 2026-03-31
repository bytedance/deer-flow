import type { KeyboardEvent } from "react";

type IMEKeyboardEvent = KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>;

export function isIMEComposing(
  event: IMEKeyboardEvent,
  isComposing = false,
): boolean {
  return isComposing || event.nativeEvent.isComposing || event.keyCode === 229;
}
