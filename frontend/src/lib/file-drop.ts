import { isDesktop, type TauriRuntime } from "./is-desktop.js";
import {
  readDroppedFiles,
  type DesktopDroppedFilePayload,
} from "./tauri.js";

const DEFAULT_BROWSER_DROP_SUPPRESSION_WINDOW_MS = 300;

const MIME_TYPES_BY_EXTENSION: Record<string, string> = {
  csv: "text/csv",
  gif: "image/gif",
  heic: "image/heic",
  jpeg: "image/jpeg",
  jpg: "image/jpeg",
  json: "application/json",
  md: "text/markdown",
  pdf: "application/pdf",
  png: "image/png",
  svg: "image/svg+xml",
  txt: "text/plain",
  webp: "image/webp",
};

type ResolveDesktopDroppedFilesOptions = {
  isDesktop?: () => boolean;
  loadDroppedFiles?: (
    paths: string[],
  ) => Promise<readonly DesktopDroppedFilePayload[] | undefined>;
};

function defaultIsDesktop(runtime: TauriRuntime = globalThis): boolean {
  return isDesktop(runtime);
}

function basename(path: string): string {
  return path.split(/[/\\]/).at(-1) ?? path;
}

function inferMimeType(
  name: string,
  mimeType?: string | null,
): string {
  const normalizedType = mimeType?.trim();
  if (normalizedType) {
    return normalizedType;
  }

  const extension = name.split(".").at(-1)?.toLowerCase();
  if (!extension) {
    return "";
  }

  return MIME_TYPES_BY_EXTENSION[extension] ?? "";
}

export function filterDroppedPaths(paths: readonly string[]): string[] {
  const seen = new Set<string>();
  const filtered: string[] = [];

  for (const path of paths) {
    const normalizedPath = path.trim();

    if (!normalizedPath || seen.has(normalizedPath)) {
      continue;
    }

    seen.add(normalizedPath);
    filtered.push(normalizedPath);
  }

  return filtered;
}

export function shouldSuppressBrowserDrop(
  lastNativeDropAt: number | null | undefined,
  now = Date.now(),
  windowMs = DEFAULT_BROWSER_DROP_SUPPRESSION_WINDOW_MS,
): boolean {
  if (lastNativeDropAt == null) {
    return false;
  }

  return now - lastNativeDropAt <= windowMs;
}

function mapDesktopDroppedFilesToFiles(
  droppedFiles: readonly DesktopDroppedFilePayload[],
): File[] {
  return droppedFiles.map((file) => {
    const name = file.name || basename(file.path);

    return new File([Uint8Array.from(file.bytes)], name, {
      type: inferMimeType(name, file.mimeType),
    });
  });
}

export async function resolveDesktopDroppedFiles(
  paths: readonly string[],
  options: ResolveDesktopDroppedFilesOptions = {},
): Promise<File[]> {
  const detectDesktop = options.isDesktop ?? defaultIsDesktop;

  if (!detectDesktop()) {
    return [];
  }

  const filteredPaths = filterDroppedPaths(paths);
  if (filteredPaths.length === 0) {
    return [];
  }

  const droppedFiles =
    (await (options.loadDroppedFiles ??
      ((nextPaths) => readDroppedFiles(nextPaths, { isDesktop: detectDesktop })))(
      filteredPaths,
    )) ?? [];

  return mapDesktopDroppedFilesToFiles(droppedFiles);
}
