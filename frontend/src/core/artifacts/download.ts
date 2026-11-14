import { fetch } from "@/core/api/fetcher";

export const MAX_BUFFERED_DOWNLOAD_BYTES = 64 * 1024 * 1024;

/** Large/unknown streams fall back to the browser's disk-backed download path. */
export async function prepareArtifactDownload(
  url: string,
  signal: AbortSignal,
): Promise<Blob | null> {
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error(`Download failed (${response.status})`);
  }
  if (
    Number(response.headers.get("content-length")) > MAX_BUFFERED_DOWNLOAD_BYTES
  ) {
    await response.body?.cancel();
    return null;
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Download body unavailable");
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  try {
    while (true) {
      signal.throwIfAborted();
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BUFFERED_DOWNLOAD_BYTES) return null;
      chunks.push(new Uint8Array(value));
    }
    signal.throwIfAborted();
    return new Blob(chunks, {
      type: response.headers.get("content-type") ?? "application/octet-stream",
    });
  } finally {
    try {
      await reader.cancel();
    } finally {
      reader.releaseLock();
    }
  }
}
