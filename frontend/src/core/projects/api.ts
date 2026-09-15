import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  Project,
  ProjectCreateInput,
  ProjectPatchInput,
  ProjectStatus,
  ProjectThread,
} from "./types";

export type ProjectListResponse = {
  projects: Project[];
};

export const PROJECTS_QUERY_KEY = ["projects"] as const;

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
