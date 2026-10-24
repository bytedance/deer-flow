import { captureWorkspaceRequestScope } from "@/core/workspaces/request-scope";
import type { WorkspaceLifetime } from "@/core/workspaces/session";

import { ArtifactRequestError } from "./api";
import { requestArtifact } from "./request";
import { resolveHTMLArtifactResourceURL } from "./utils";

export interface HTMLArtifactResource {
  readonly url: string;
  readonly bytes: ArrayBuffer;
  readonly contentType: string;
  readonly status: number;
}

/** One report document owns its reads; this object grants no new backend rights. */
export function createHTMLArtifactResourceReader({
  sourceURL,
  lifetime,
}: {
  sourceURL: string;
  lifetime: Pick<WorkspaceLifetime, "scope" | "rest">;
}) {
  const scope = captureWorkspaceRequestScope(lifetime.scope);
  const rest = lifetime.rest;
  const documentController = new AbortController();
  const source = resolveHTMLArtifactResourceURL(
    sourceURL,
    sourceURL,
    scope.workspaceId,
  );
  if (!source)
    throw new TypeError("HTML preview requires a native artifact source");
  const signalFor = (signal?: AbortSignal) =>
    AbortSignal.any([
      scope.signal,
      documentController.signal,
      ...(signal ? [signal] : []),
    ]);
  signalFor().throwIfAborted();
  const resolve = (reference: string, baseURL = source) =>
    resolveHTMLArtifactResourceURL(
      reference,
      source,
      scope.workspaceId,
      baseURL,
    );
  return Object.freeze({
    sourceURL: source,
    resolve,
    async read(
      reference: string,
      options?: { baseURL?: string; signal?: AbortSignal },
    ): Promise<HTMLArtifactResource> {
      const signal = signalFor(options?.signal);
      signal.throwIfAborted();
      const url = resolve(reference, options?.baseURL);
      if (!url)
        throw new TypeError(
          "HTML resources must stay in the source thread artifact route",
        );
      const requestURL = new URL(url);
      requestURL.hash = "";
      return requestArtifact(
        requestURL.href,
        { method: "GET", cache: "no-store", redirect: "error" },
        async (response) => {
          if (!response.ok) {
            await response.body?.cancel().catch(() => undefined);
            throw new ArtifactRequestError(
              response.status,
              "Failed to load HTML artifact resource",
            );
          }
          return {
            url,
            bytes: await response.arrayBuffer(),
            contentType:
              response.headers.get("Content-Type") ??
              "application/octet-stream",
            status: response.status,
          };
        },
        { rest, signal },
      );
    },
    dispose() {
      documentController.abort();
    },
  });
}
