import { isDesktop, type TauriRuntime } from "./is-desktop.js";

type TauriCommandArgs = Record<string, unknown>;

type TauriInvoke = (command: string, args?: TauriCommandArgs) => Promise<string>;

type TauriCoreModule = {
  invoke: TauriInvoke;
};

export type LoadTauriCore = () => Promise<TauriCoreModule>;

type TauriBridgeOptions = {
  isDesktop?: () => boolean;
  loadCore?: LoadTauriCore;
};

const loadTauriCore: LoadTauriCore = () => import("@tauri-apps/api/core");

function defaultIsDesktop(runtime: TauriRuntime = globalThis): boolean {
  return isDesktop(runtime);
}

async function invokeDesktopCommand(
  command: string,
  args: TauriCommandArgs | undefined,
  options: TauriBridgeOptions = {},
): Promise<string | undefined> {
  const detectDesktop = options.isDesktop ?? defaultIsDesktop;

  if (!detectDesktop()) {
    return undefined;
  }

  const { invoke } = await (options.loadCore ?? loadTauriCore)();

  return invoke(command, args);
}

export function openNewChatWindow(
  options?: TauriBridgeOptions,
): Promise<string | undefined> {
  return invokeDesktopCommand("open_new_chat_window", undefined, options);
}

export function openThreadInNewWindow(
  threadId: string,
  options?: TauriBridgeOptions,
): Promise<string | undefined> {
  return invokeDesktopCommand("open_thread_window", { threadId }, options);
}
