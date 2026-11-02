import type { PluginSurface, SurfaceContext } from "./contracts";

/** Shadow DOM scopes styles, not privileges: packages are administrator-trusted code. */
export function mountSurface(
  container: HTMLElement,
  surface: PluginSurface,
  context: Omit<SurfaceContext, "signal" | "openConversation"> & {
    openConversation?: (threadId: string, signal: AbortSignal) => Promise<void>;
  },
  onError: () => void,
) {
  const abort = new AbortController();
  const shadow =
    container.shadowRoot ?? container.attachShadow({ mode: "open" });
  const root = document.createElement("div");
  shadow.replaceChildren(root);
  let controller: { dispose: () => void } | undefined;
  const cleanup = () => {
    if (abort.signal.aborted) return;
    abort.abort();
    try {
      controller?.dispose();
    } catch {
      /* Contain plugin cleanup failures. */
    }
    root.remove();
  };
  try {
    controller = surface.mount(root, {
      ...context,
      signal: abort.signal,
      requestBackend: context.requestBackend
        ? async (path, options) => {
            abort.signal.throwIfAborted();
            const response = await context.requestBackend!(path, {
              ...options,
              signal: options?.signal
                ? AbortSignal.any([abort.signal, options.signal])
                : abort.signal,
            });
            abort.signal.throwIfAborted();
            return response;
          }
        : undefined,
      openConversation: context.openConversation
        ? async (threadId) => {
            abort.signal.throwIfAborted();
            await context.openConversation!(threadId, abort.signal);
          }
        : undefined,
      async callBackend(action, payload) {
        abort.signal.throwIfAborted();
        const result = await context.callBackend(action, payload);
        abort.signal.throwIfAborted();
        return result;
      },
    });
    if (typeof controller?.dispose !== "function")
      throw new Error("Invalid surface controller");
  } catch {
    cleanup();
    onError();
  }
  return cleanup;
}
