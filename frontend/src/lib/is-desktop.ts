export type TauriRuntime = typeof globalThis & {
  __TAURI__?: unknown;
  __TAURI_INTERNALS__?: unknown;
};

export function isDesktop(runtime: TauriRuntime = globalThis): boolean {
  return (
    runtime.__TAURI__ !== undefined || runtime.__TAURI_INTERNALS__ !== undefined
  );
}
