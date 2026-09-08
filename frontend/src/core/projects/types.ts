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
