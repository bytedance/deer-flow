import { cn } from "@/lib/utils";

export const CHAT_COMPOSER_INPUT_BOX_CLASSNAME = "bg-background/5 w-full";

export function getChatComposerDockClassName(isNewThread = false): string {
  return cn(
    "z-30 flex justify-center px-4",
    isNewThread
      ? "relative w-full py-10"
      : "absolute right-0 bottom-0 left-0 -translate-y-4",
  );
}

export function getChatComposerFrameClassName(isNewThread: boolean): string {
  return cn(
    "relative w-full",
    isNewThread
      ? "max-w-(--container-width-sm)"
      : "max-w-(--container-width-md)",
  );
}
