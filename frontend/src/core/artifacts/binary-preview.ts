import { fetch } from "@/core/api/fetcher";

export const MAX_BINARY_PREVIEW_BYTES = 25 * 1024 * 1024;

/** Bounded even when Content-Length is absent or misleading. */
export async function readPreviewFile(
  url: string,
  signal: AbortSignal,
): Promise<{ bytes: ArrayBuffer; etag: string | null }> {
  signal.throwIfAborted();
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Preview unavailable (${response.status})`);
  const size = Number(response.headers.get("content-length"));
  if (size > MAX_BINARY_PREVIEW_BYTES) {
    await response.body?.cancel();
    throw new Error("Preview file too large");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Preview body unavailable");
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      signal.throwIfAborted();
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > MAX_BINARY_PREVIEW_BYTES)
        throw new Error("Preview file too large");
      chunks.push(value);
    }
    signal.throwIfAborted();
  } finally {
    try {
      await reader.cancel();
    } finally {
      reader.releaseLock();
    }
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { bytes: bytes.buffer, etag: response.headers.get("etag") };
}
