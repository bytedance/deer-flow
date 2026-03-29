import { openThreadInNewWindow } from "../../lib/tauri.js";

type OpenThreadInNewWindow = typeof openThreadInNewWindow;

export function shouldShowOpenInNewWindowAction(options: {
  isDesktop: boolean;
  staticWebsiteOnly: string | undefined;
}): boolean {
  return options.staticWebsiteOnly !== "true" && options.isDesktop;
}

export function openRecentChatInNewWindow(
  threadId: string,
  options: {
    isDesktop: boolean;
    openThreadInNewWindow?: OpenThreadInNewWindow;
  },
): Promise<string | undefined> {
  if (!options.isDesktop) {
    return Promise.resolve(undefined);
  }

  return (options.openThreadInNewWindow ?? openThreadInNewWindow)(threadId);
}
