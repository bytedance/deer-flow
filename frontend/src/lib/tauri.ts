import { isDesktop, type TauriRuntime } from "./is-desktop.js";

type TauriCommandArgs = Record<string, unknown>;

type TauriInvoke = <T>(
  command: string,
  args?: TauriCommandArgs,
) => Promise<T>;

type TauriCoreModule = {
  invoke: TauriInvoke;
};

export type LoadTauriCore = () => Promise<TauriCoreModule>;

export type DesktopDroppedFilePayload = {
  bytes: number[];
  mimeType?: string | null;
  name: string;
  path: string;
};

type TauriDropPayload =
  | {
      paths: string[];
      position: unknown;
      type: "drop";
    }
  | {
      paths: string[];
      position: unknown;
      type: "enter";
    }
  | {
      position: unknown;
      type: "over";
    }
  | {
      type: "leave";
    };

export type NativeFileDropEvent = {
  payload: TauriDropPayload;
};

type TauriWindowHandle = {
  onDragDropEvent: (
    handler: (event: NativeFileDropEvent) => void,
  ) => Promise<() => void>;
};

type TauriWindowModule = {
  getCurrentWindow: () => TauriWindowHandle;
};

export type LoadTauriWindow = () => Promise<TauriWindowModule>;

type TauriBridgeOptions = {
  isDesktop?: () => boolean;
  loadCore?: LoadTauriCore;
};

type TauriWindowBridgeOptions = TauriBridgeOptions & {
  loadWindow?: LoadTauriWindow;
};

const loadTauriCore: LoadTauriCore = () => import("@tauri-apps/api/core");
const loadTauriWindow: LoadTauriWindow = () => import("@tauri-apps/api/window");

function defaultIsDesktop(runtime: TauriRuntime = globalThis): boolean {
  return isDesktop(runtime);
}

async function invokeDesktopCommand<T>(
  command: string,
  args: TauriCommandArgs | undefined,
  options: TauriBridgeOptions = {},
): Promise<T | undefined> {
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
  return invokeDesktopCommand<string>("open_new_chat_window", undefined, options);
}

export function openThreadInNewWindow(
  threadId: string,
  options?: TauriBridgeOptions,
): Promise<string | undefined> {
  return invokeDesktopCommand<string>("open_thread_window", { threadId }, options);
}

export function readDroppedFiles(
  paths: string[],
  options?: TauriBridgeOptions,
): Promise<DesktopDroppedFilePayload[] | undefined> {
  return invokeDesktopCommand<DesktopDroppedFilePayload[]>(
    "read_dropped_files",
    { paths },
    options,
  );
}

export async function listenForNativeFileDrop(
  handler: (event: NativeFileDropEvent) => void,
  options: TauriWindowBridgeOptions = {},
): Promise<(() => void) | undefined> {
  const detectDesktop = options.isDesktop ?? defaultIsDesktop;

  if (!detectDesktop()) {
    return undefined;
  }

  const { getCurrentWindow } = await (options.loadWindow ?? loadTauriWindow)();

  return getCurrentWindow().onDragDropEvent(handler);
}
