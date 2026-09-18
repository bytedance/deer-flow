import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import {
  ARTIFACT_PREVIEW_MAX_BYTES,
  parseContentRange,
} from "@/core/artifacts/loader";
import { getBackendBaseURL } from "@/core/config";

import type {
  AttachProjectDocumentResult,
  Project,
  ProjectCreateInput,
  ProjectDocument,
  ProjectPatchInput,
  ProjectStatus,
  ProjectThread,
  ProjectThreadFileGroup,
  PromoteThreadFileInput,
} from "./types";

export type ProjectListResponse = {
  projects: Project[];
};

/** ``GET /api/projects/{id}/documents`` envelope (spec §6.5). */
export type ProjectDocumentListResponse = {
  documents: ProjectDocument[];
  total: number;
  limit: number;
  offset: number;
};

/**
 * Upload/promote response: ``deduplicated`` distinguishes the 200 dedup hit
 * (existing row, first name wins, §10.9) from the 201 created row.
 */
export type ProjectDocumentUploadResponse = {
  document: ProjectDocument;
  deduplicated: boolean;
};

/** ``GET /api/projects/{id}/thread-files`` envelope (spec §7.4). */
export type ProjectThreadFilesResponse = {
  groups: ProjectThreadFileGroup[];
  next_offset: number | null;
  truncated: boolean;
};

export const PROJECTS_QUERY_KEY = ["projects"] as const;

/** ``GET /api/projects/config`` payload (spec §6.5). */
export type ProjectsConfig = {
  instructions_max_bytes: number;
  trash_retention_days: number;
};

/**
 * Client mirror of the server defaults (config/projects_config.py): callers
 * fall back to these when the config endpoint is unavailable (older gateway,
 * network failure), matching what an unconfigured server enforces.
 */
export const PROJECTS_CONFIG_DEFAULT: ProjectsConfig = {
  instructions_max_bytes: 8192,
  trash_retention_days: 30,
};

/** Server-configured projects limits; shared by the editor and trash. */
export async function getProjectsConfig(): Promise<ProjectsConfig> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/projects/config`,
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load projects config."),
    );
  }

  return (await response.json()) as ProjectsConfig;
}

async function readProjectAPIError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // Fall through to the caller-provided message.
  }
  return fallback;
}

function projectUrl(projectId: string, suffix = ""): string {
  return `${getBackendBaseURL()}/api/projects/${encodeURIComponent(projectId)}${suffix}`;
}

export async function listProjects(status?: ProjectStatus): Promise<Project[]> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/projects${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load projects."),
    );
  }

  const body = (await response.json()) as ProjectListResponse;
  return body.projects;
}

export async function getProject(projectId: string): Promise<Project> {
  const response = await fetchWithAuth(projectUrl(projectId), {
    method: "GET",
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load project."),
    );
  }

  return (await response.json()) as Project;
}

export async function createProject(
  input: ProjectCreateInput,
): Promise<Project> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}/api/projects`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: input.name,
      instructions: input.instructions ?? "",
      presentation: input.presentation ?? {},
    }),
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to create project."),
    );
  }

  return (await response.json()) as Project;
}

export async function patchProject(
  projectId: string,
  input: ProjectPatchInput,
): Promise<Project> {
  const response = await fetchWithAuth(projectUrl(projectId), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...(input.name !== undefined ? { name: input.name } : {}),
      ...(input.instructions !== undefined
        ? { instructions: input.instructions }
        : {}),
      ...(input.presentation !== undefined
        ? { presentation: input.presentation }
        : {}),
    }),
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to update project."),
    );
  }

  return (await response.json()) as Project;
}

export async function archiveProject(projectId: string): Promise<Project> {
  const response = await fetchWithAuth(projectUrl(projectId, "/archive"), {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to archive project."),
    );
  }

  return (await response.json()) as Project;
}

export async function restoreProject(projectId: string): Promise<Project> {
  const response = await fetchWithAuth(projectUrl(projectId, "/restore"), {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to restore project."),
    );
  }

  return (await response.json()) as Project;
}

export async function deleteProject(projectId: string): Promise<void> {
  const response = await fetchWithAuth(projectUrl(projectId), {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to delete project."),
    );
  }
}

export async function listProjectThreads(
  projectId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ProjectThread[]> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetchWithAuth(
    projectUrl(projectId, `/threads${query}`),
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load project threads."),
    );
  }

  return (await response.json()) as ProjectThread[];
}

export async function listProjectDocuments(
  projectId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ProjectDocumentListResponse> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetchWithAuth(
    projectUrl(projectId, `/documents${query}`),
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load project documents."),
    );
  }

  return (await response.json()) as ProjectDocumentListResponse;
}

/**
 * Shelf exactly one file per request (spec §17.2); the UI loops for
 * multi-file drops. 201 created and 200 dedup hit are both success.
 */
export async function uploadProjectDocument(
  projectId: string,
  { file, name }: { file: File; name?: string },
): Promise<ProjectDocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (name !== undefined) {
    formData.append("name", name);
  }
  const response = await fetchWithAuth(projectUrl(projectId, "/documents"), {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to upload project document."),
    );
  }

  return (await response.json()) as ProjectDocumentUploadResponse;
}

/** Save a thread file (upload or output) onto the project shelf (spec §7.4). */
export async function promoteThreadFile(
  projectId: string,
  input: PromoteThreadFileInput,
): Promise<ProjectDocumentUploadResponse> {
  const response = await fetchWithAuth(
    projectUrl(projectId, "/documents/from-thread"),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        thread_id: input.thread_id,
        kind: input.kind,
        name: input.name,
        ...(input.shelf_name !== undefined
          ? { shelf_name: input.shelf_name }
          : {}),
      }),
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to save file to project."),
    );
  }

  return (await response.json()) as ProjectDocumentUploadResponse;
}

/** Attach a shelf document into a thread through the uploads path (§7.3). */
export async function attachProjectDocument(
  projectId: string,
  documentId: string,
  threadId: string,
): Promise<AttachProjectDocumentResult> {
  const response = await fetchWithAuth(
    projectUrl(
      projectId,
      `/documents/${encodeURIComponent(documentId)}/attach-to-thread/${encodeURIComponent(threadId)}`,
    ),
    {
      method: "POST",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(
        response,
        "Failed to attach document to thread.",
      ),
    );
  }

  return (await response.json()) as AttachProjectDocumentResult;
}

/** Move one shelf document to trash (204; restore/purge are the trash tier). */
export async function deleteProjectDocument(
  projectId: string,
  documentId: string,
): Promise<void> {
  const response = await fetchWithAuth(
    projectUrl(projectId, `/documents/${encodeURIComponent(documentId)}`),
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to delete project document."),
    );
  }
}

/**
 * Content endpoint address (spec §6.5): inline text by default, forced
 * attachment with ``download`` — used for the shelf row's download action.
 */
export function urlOfProjectDocumentContent(
  projectId: string,
  documentId: string,
  { download = false }: { download?: boolean } = {},
): string {
  const suffix = `/documents/${encodeURIComponent(documentId)}/content${download ? "?download=true" : ""}`;
  return projectUrl(projectId, suffix);
}

/**
 * Content-missing conflict (HTTP 409 ``content_missing``, spec §11): the
 * row's bytes are gone or damaged, so the page renders the row as
 * content-missing with move-to-trash as its only action.
 */
export class ProjectDocumentContentMissingError extends Error {
  constructor() {
    super("content_missing");
    this.name = "ProjectDocumentContentMissingError";
  }
}

/** Media types the preview dialog decodes as text (bounded prefix only). */
function isTextPreviewMediaType(contentType: string): boolean {
  return (
    contentType.startsWith("text/") ||
    contentType === "application/json" ||
    contentType === "application/xml" ||
    contentType === "application/javascript" ||
    contentType === "application/x-yaml" ||
    contentType === "application/yaml"
  );
}

/**
 * Active-content media types — mirror of the backend's
 * ``deerflow.utils.text_detection._is_active_content_mime_type``: any
 * WHATWG XML type (plus ``text/html``/``text/xsl``) can carry script, so the
 * content endpoint always serves them as an attachment. The preview must
 * never navigate its sandboxed iframe to one (the empty sandbox blocks the
 * download and renders a blank frame).
 */
const ACTIVE_CONTENT_MEDIA_TYPES = new Set([
  "text/html",
  "application/xhtml+xml",
  "image/svg+xml",
  "text/xml",
  "application/xml",
  "text/xsl",
]);

function isActiveContentMediaType(contentType: string): boolean {
  return (
    ACTIVE_CONTENT_MEDIA_TYPES.has(contentType) || contentType.endsWith("+xml")
  );
}

/**
 * Media types the browser renders inline inside the sandboxed iframe —
 * passive binaries only; the active-content XML family (SVG included) is
 * excluded because the endpoint serves it as an attachment. PDF is handled
 * separately (its own preview kind): Chromium blocks the built-in PDF
 * viewer inside ``sandbox=""``, so PDFs render in an unsandboxed iframe.
 */
function isBrowserViewableMediaType(contentType: string): boolean {
  if (isActiveContentMediaType(contentType)) {
    return false;
  }
  return (
    contentType.startsWith("image/") ||
    contentType.startsWith("audio/") ||
    contentType.startsWith("video/")
  );
}

/**
 * Preview payload for the shelf preview dialog (§6.5). Binary documents are
 * never text-decoded: browser-viewable kinds render the content URL in a
 * sandboxed iframe, PDFs render in an iframe WITHOUT the sandbox attribute
 * (Chromium blocks its built-in viewer inside ``sandbox=""``), everything
 * else gets an explicit download fallback.
 */
export type ProjectDocumentPreview =
  | {
      kind: "text";
      content: string;
      truncated: boolean;
      previewBytes: number;
      totalBytes: number | undefined;
    }
  | { kind: "binary" }
  | { kind: "pdf" }
  | { kind: "unsupported" };
/**
 * Fetch a shelf document for the preview dialog (§6.5). The request asks for
 * at most the first ``ARTIFACT_PREVIEW_MAX_BYTES`` through an HTTP byte range
 * (the content endpoint is a Starlette ``FileResponse``, which answers 206);
 * an oversized ``Content-Length`` on a 200 still marks the preview truncated
 * so the dialog offers the explicit full-file action instead of rendering a
 * partial file as complete. The response media type is inspected before any
 * decode: only textual types are decoded, never binary bytes.
 */
export async function fetchProjectDocumentPreview(
  projectId: string,
  documentId: string,
): Promise<ProjectDocumentPreview> {
  const response = await fetchWithAuth(
    urlOfProjectDocumentContent(projectId, documentId),
    {
      headers: { Range: `bytes=0-${ARTIFACT_PREVIEW_MAX_BYTES - 1}` },
    },
  );
  if (response.status === 409) {
    throw new ProjectDocumentContentMissingError();
  }
  const contentRange = parseContentRange(response.headers.get("Content-Range"));
  if (response.status === 416 && contentRange?.total === 0) {
    return {
      kind: "text",
      content: "",
      truncated: false,
      previewBytes: 0,
      totalBytes: 0,
    };
  }
  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load document content."),
    );
  }

  const contentType = (response.headers.get("Content-Type") ?? "")
    .split(";")[0]!
    .trim()
    .toLowerCase();
  if (contentType === "application/pdf") {
    // PDFs get their own kind: the dialog renders them in an iframe WITHOUT
    // the sandbox attribute (Chromium blocks its built-in viewer inside
    // ``sandbox=""``), unlike other viewable binaries. The bounded prefix is
    // useless either way — release the body instead of decoding it.
    await response.body?.cancel();
    return { kind: "pdf" };
  }
  if (isBrowserViewableMediaType(contentType)) {
    // The bounded prefix is useless to the iframe, which loads the content
    // URL itself; release the body instead of decoding it.
    await response.body?.cancel();
    return { kind: "binary" };
  }
  if (!isTextPreviewMediaType(contentType)) {
    await response.body?.cancel();
    return { kind: "unsupported" };
  }

  const bytes = await response.arrayBuffer();
  const contentLengthHeader = response.headers.get("Content-Length");
  const contentLength =
    contentLengthHeader === null ? undefined : Number(contentLengthHeader);
  const totalBytes =
    contentRange?.total ??
    (contentLength !== undefined && Number.isFinite(contentLength)
      ? contentLength
      : undefined);
  const previewBytes = Math.min(bytes.byteLength, ARTIFACT_PREVIEW_MAX_BYTES);
  const truncated =
    (response.status === 206 &&
      (contentRange?.end === undefined ||
        contentRange.total > contentRange.end + 1)) ||
    bytes.byteLength > ARTIFACT_PREVIEW_MAX_BYTES ||
    (totalBytes !== undefined &&
      totalBytes > ARTIFACT_PREVIEW_MAX_BYTES &&
      totalBytes > bytes.byteLength);
  // Streaming decode intentionally holds an incomplete trailing UTF-8 code
  // point instead of fabricating U+FFFD at the range boundary.
  const content = new TextDecoder().decode(
    bytes.byteLength > ARTIFACT_PREVIEW_MAX_BYTES
      ? bytes.slice(0, ARTIFACT_PREVIEW_MAX_BYTES)
      : bytes,
    { stream: truncated },
  );
  return { kind: "text", content, truncated, previewBytes, totalBytes };
}

/** Read-only conversation-files view over member threads (spec §7.4). */
export async function listProjectThreadFiles(
  projectId: string,
  params: {
    offset?: number;
    thread_limit?: number;
    file_limit?: number;
  } = {},
): Promise<ProjectThreadFilesResponse> {
  const search = new URLSearchParams();
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }
  if (params.thread_limit !== undefined) {
    search.set("thread_limit", String(params.thread_limit));
  }
  if (params.file_limit !== undefined) {
    search.set("file_limit", String(params.file_limit));
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetchWithAuth(
    projectUrl(projectId, `/thread-files${query}`),
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load thread files."),
    );
  }

  return (await response.json()) as ProjectThreadFilesResponse;
}
