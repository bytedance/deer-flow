import { fetch, type WorkspaceRESTClient } from "@/core/api/fetcher";

export interface ArtifactRequestOptions {
  rest: WorkspaceRESTClient;
  signal?: AbortSignal;
}

/** Keep native decoding, including errors and async hashing, inside the lease. */
export async function requestArtifact<T>(
  url: string,
  init: RequestInit | undefined,
  decode: (response: Response) => Promise<T>,
  options?: ArtifactRequestOptions,
): Promise<T> {
  options?.signal?.throwIfAborted();
  const transport = options?.rest.fetch ?? fetch;
  const requestInit = options?.signal
    ? { ...init, signal: options.signal }
    : init;
  const response = requestInit
    ? await transport(url, requestInit)
    : await transport(url);
  const result = options
    ? await options.rest.consume(response, decode)
    : await decode(response);
  options?.signal?.throwIfAborted();
  return result;
}
