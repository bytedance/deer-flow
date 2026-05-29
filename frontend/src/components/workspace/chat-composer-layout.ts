import { cn } from "@/lib/utils";

export const CHAT_COMPOSER_INPUT_BOX_CLASSNAME = "bg-background/5 w-full";

export function getChatComposerDockClassName(): string {
  return "absolute right-0 bottom-0 left-0 z-30 flex -translate-y-4 justify-center px-4";
}

export function getChatComposerFrameClassName(isNewThread: boolean): string {
  return cn(
    "relative w-full",
    isNewThread && "-translate-y-[calc(50vh-96px)]",
    isNewThread
      ? "max-w-(--container-width-sm)"
      : "max-w-(--container-width-md)",
  );
}
