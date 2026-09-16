import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  EmptyTrashResult,
  RestoreDocumentResult,
  TrashDocument,
} from "./types";

/** ``GET /api/trash/documents`` envelope (spec §6.5). */
export type TrashListResponse = {
  documents: TrashDocument[];
  total: number;
  limit: number;
  offset: number;
};

export const TRASH_QUERY_KEY = ["trash", "documents"] as const;

/**
 * Restore conflict (HTTP 409): the trashed row's content file is missing or
 * damaged (``content_missing``, spec §8.3), so the row stays in trash. The UI
 * surfaces this distinctly from a plain 404.
 */
export class RestoreConflictError extends Error {
  constructor(
    message: string,
    readonly detail: string,
  ) {
    super(message);
    this.name = "RestoreConflictError";
  }
}

/**
 * Restore/list-not-found (HTTP 404): either the trash row is gone or the
 * restore had no valid target (origin project gone/archived, none supplied,
 * spec §8.2). The trash view answers the no-target case with the project
 * picker and retries with an explicit ``project_id``.
 */
export class TrashNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TrashNotFoundError";
  }
}

async function readTrashAPIError(
  response: Response,
  fallback: string,
): Promise<{ message: string; detail: string }> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return { message: body.detail, detail: body.detail };
    }
  } catch {
    // Fall through to the caller-provided message.
  }
  return { message: fallback, detail: "" };
}

function trashUrl(suffix = ""): string {
  return `${getBackendBaseURL()}/api/trash${suffix}`;
}

export async function listTrashDocuments(
  params: { limit?: number; offset?: number } = {},
): Promise<TrashListResponse> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetchWithAuth(trashUrl(`/documents${query}`), {
    method: "GET",
  });

  if (!response.ok) {
    const { message } = await readTrashAPIError(
      response,
      "Failed to load trash.",
    );
    throw new Error(message);
  }

  return (await response.json()) as TrashListResponse;
}

/**
 * Restore a trashed document (spec §8.2). ``projectId`` is only needed when
 * the origin project no longer exists or is archived; otherwise the server
 * restores into the origin. 409 ``content_missing`` throws
 * ``RestoreConflictError`` so the UI can keep the row and explain why.
 */
export async function restoreTrashDocument(
  documentId: string,
  { projectId }: { projectId?: string } = {},
): Promise<RestoreDocumentResult> {
  const response = await fetchWithAuth(
    trashUrl(`/documents/${encodeURIComponent(documentId)}/restore`),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(
        projectId !== undefined ? { project_id: projectId } : {},
      ),
    },
  );

  if (!response.ok) {
    const { message, detail } = await readTrashAPIError(
      response,
      "Failed to restore document.",
    );
    if (response.status === 409) {
      throw new RestoreConflictError(message, detail);
    }
    if (response.status === 404) {
      throw new TrashNotFoundError(message);
    }
    throw new Error(message);
  }

  return (await response.json()) as RestoreDocumentResult;
}

/** Permanently purge one trashed document (204; cannot be undone, §8.3). */
export async function purgeTrashDocument(documentId: string): Promise<void> {
  const response = await fetchWithAuth(
    trashUrl(`/documents/${encodeURIComponent(documentId)}/purge`),
    {
      method: "POST",
    },
  );

  if (!response.ok) {
    const { message } = await readTrashAPIError(
      response,
      "Failed to delete document permanently.",
    );
    throw new Error(message);
  }
}

/**
 * Empty the trash: permanently delete every trashed document, regardless of
 * the retention window — the confirmation covers the whole listing, and
 * expired rows are a server-side sweep concern, never a gate on this action
 * (spec §8.3).
 */
export async function emptyTrash(): Promise<EmptyTrashResult> {
  const response = await fetchWithAuth(trashUrl("/purge"), {
    method: "POST",
  });

  if (!response.ok) {
    const { message } = await readTrashAPIError(
      response,
      "Failed to empty trash.",
    );
    throw new Error(message);
  }

  return (await response.json()) as EmptyTrashResult;
}
