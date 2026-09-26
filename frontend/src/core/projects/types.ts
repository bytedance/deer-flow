export type ProjectStatus = "active" | "archived";

export type ProjectPresentation = {
  icon?: string;
  color?: string;
};

export type Project = {
  id: string;
  name: string;
  instructions: string;
  presentation: ProjectPresentation;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
};

export type ProjectCreateInput = {
  name: string;
  instructions?: string;
  presentation?: ProjectPresentation;
};

export type ProjectPatchInput = {
  name?: string;
  instructions?: string;
  presentation?: ProjectPresentation;
};

/**
 * A thread row as returned by ``GET /api/projects/{id}/threads``: the thread
 * metadata store's search shape (``metadata`` carries
 * ``deerflow_project_id``; ``display_name`` is the wire title).
 */
export type ProjectThread = {
  thread_id: string;
  display_name?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
};

export type ProjectDocumentSourceKind = "upload" | "output";

/**
 * One active shelf row as returned by the project documents API
 * (``ProjectDocumentResponse``, spec §6.5). Internal columns (``user_id``,
 * ``stored_relpath``, trash fields) never leave the server.
 */
export type ProjectDocument = {
  id: string;
  name: string;
  size_bytes: number;
  sha256: string;
  /**
   * Read-time integrity (§11): true when the row's original bytes are
   * missing or size-mismatched. Authoritative at list render — the row
   * shows the content-missing badge without any preview probe.
   */
  content_missing: boolean;
  source_thread_id: string | null;
  source_kind: ProjectDocumentSourceKind | null;
  source_name: string | null;
  created_at: string;
  updated_at: string;
};

/**
 * Body of ``POST /api/projects/{id}/documents/from-thread`` (spec §6.5):
 * ``name`` locates the source file inside the thread, ``shelf_name`` is the
 * optional display name on the shelf (defaults to ``name``).
 */
export type PromoteThreadFileInput = {
  thread_id: string;
  kind: ProjectDocumentSourceKind;
  name: string;
  shelf_name?: string;
};

/**
 * Result of ``POST …/documents/{document_id}/attach-to-thread/{thread_id}``:
 * the ingested thread upload the composer adds to its attachment list.
 */
export type AttachProjectDocumentResult = {
  filename: string;
  size_bytes: number;
  virtual_path: string;
  artifact_url: string;
};

/** One file entry inside a member thread of the conversation-files view. */
export type ProjectThreadFile = {
  kind: ProjectDocumentSourceKind;
  name: string;
  size_bytes: number;
  modified_at: string;
  artifact_url: string;
};

/** One member-thread group of the conversation-files view (spec §7.4). */
export type ProjectThreadFileGroup = {
  thread_id: string;
  /**
   * The member thread's title. Nullable on the wire like ``ProjectThread``:
   * the thread meta row starts as ``null`` and is filled by title generation.
   */
  display_name?: string | null;
  updated_at: string;
  files: ProjectThreadFile[];
  /** True when the thread's files were cut at the request's file_limit. */
  truncated: boolean;
};
