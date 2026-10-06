import { fetch as authFetch } from "@/core/api/fetcher";

import { getBackendBaseURL } from "../config";

import type {
  RagAsrProbeRequest,
  RagAsrProbeResponse,
  RagConfigInput,
  RagConfigView,
  RagConnectivityProbeRequest,
  RagConnectivityProbeResponse,
  RagDimensionProbeRequest,
  RagDimensionProbeResponse,
  RagMigrationStatus,
  RagSparseProbeRequest,
  RagSparseProbeResponse,
  RagSparseServiceProbeRequest,
  RagSparseServiceProbeResponse,
} from "./types";

/**
 * Admin RAG functional-model configuration client (spec 2026-09-10 §4).
 *
 * Both routes are admin-gated server-side; a 403 is surfaced as
 * {@link RagConfigRequestError} with `isAdminRequired` so the settings view can render
 * its denial state instead of an error toast.
 */

/** Sentinel the server echoes in place of a stored secret, and accepts on write to keep it. */
export const MASKED_RAG_SECRET = "********";

export class RagConfigRequestError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "RagConfigRequestError";
    this.status = status;
  }
  get isAdminRequired(): boolean {
    return this.status === 403;
  }
}

async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  return typeof error.detail === "string" ? error.detail : fallback;
}

export async function loadRagConfig(): Promise<RagConfigView> {
  const response = await authFetch(`${getBackendBaseURL()}/api/rag/config`);
  if (!response.ok) {
    throw new RagConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to load the RAG configuration"),
    );
  }
  return response.json() as Promise<RagConfigView>;
}

export async function saveRagConfig(
  input: RagConfigInput,
): Promise<RagConfigView> {
  const response = await authFetch(`${getBackendBaseURL()}/api/rag/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new RagConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to save the RAG configuration"),
    );
  }
  return response.json() as Promise<RagConfigView>;
}

/**
 * Where the width migration stands (spec 2026-09-26 D5-7): `null` means none ever ran, which
 * is the normal state of a deployment that never touched the width.
 */
export async function loadRagMigrationStatus(): Promise<RagMigrationStatus | null> {
  const response = await authFetch(
    `${getBackendBaseURL()}/api/rag/config/migration`,
  );
  if (!response.ok) {
    throw new RagConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to load the migration status"),
    );
  }
  return response.json() as Promise<RagMigrationStatus | null>;
}

/**
 * Ask the server whether one *candidate* model returns the sparse half (spec 2026-09-16 §3 D3).
 *
 * Read-only by design: the call runs one real embedding and writes nothing, so a refusal here is
 * an answer, not a change. It is admin-gated like the rest of the section.
 */
export async function probeEmbeddingCapability(
  input: RagSparseProbeRequest,
): Promise<RagSparseProbeResponse> {
  const response = await authFetch(
    `${getBackendBaseURL()}/api/rag/config/probe-embedding`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    throw new RagConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to probe the embedding model"),
    );
  }
  return response.json() as Promise<RagSparseProbeResponse>;
}

/**
 * Ask the server which widths a *candidate* model accepts (spec 2026-09-26 §3).
 *
 * Read-only like its siblings: real calls, nothing written. `status: "unreachable"` is a state
 * the row renders (未探明), not an error to dismiss.
 */
export async function probeEmbeddingDimensions(
  input: RagDimensionProbeRequest,
): Promise<RagDimensionProbeResponse> {
  const response = await authFetch(
    `${getBackendBaseURL()}/api/rag/config/probe-dimensions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    throw new RagConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to probe the embedding dimensions"),
    );
  }
  return response.json() as Promise<RagDimensionProbeResponse>;
}

/**
 * Reach one leg once and report how it went (spec §3 连通探针 D5-5): `dimension_unavailable`
 * keeps "it answered, but not with our width" apart from "it never answered".
 */
export async function probeLegConnectivity(
  input: RagConnectivityProbeRequest,
): Promise<RagConnectivityProbeResponse> {
  const response = await authFetch(
    `${getBackendBaseURL()}/api/rag/config/probe-connectivity`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    throw new RagConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to probe the leg"),
    );
  }
  return response.json() as Promise<RagConnectivityProbeResponse>;
}

/**
 * Ask the server whether an ASR service returns *real* segment timestamps (spec 2026-09-28 D7).
 *
 * Read-only like its siblings: one real transcription of the built-in fixture, nothing written.
 * The verdict rides in `status` and the server's own words ride in `detail`.
 */
export async function probeAsrService(
  input: RagAsrProbeRequest,
): Promise<RagAsrProbeResponse> {
  const response = await authFetch(
    `${getBackendBaseURL()}/api/rag/config/probe-asr`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    throw new RagConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to probe the ASR service"),
    );
  }
  return response.json() as Promise<RagAsrProbeResponse>;
}

/**
 * Ask the server whether the configured *external sparse service* answers (connectivity spec §3 D1).
 *
 * Read-only like its sibling: one real `/embed_sparse` call, nothing written. The answer says
 * whether the service is reachable and whether it returned any terms.
 */
export async function probeSparseService(
  input: RagSparseServiceProbeRequest,
): Promise<RagSparseServiceProbeResponse> {
  const response = await authFetch(
    `${getBackendBaseURL()}/api/rag/config/probe-sparse`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    throw new RagConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to probe the sparse service"),
    );
  }
  return response.json() as Promise<RagSparseServiceProbeResponse>;
}
