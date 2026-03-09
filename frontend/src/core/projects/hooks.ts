import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { authFetch } from "../auth/fetch";

import type { Project } from "./types";

export function useProjects() {
  return useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: async () => {
      const response = await authFetch("/api/projects");
      if (!response.ok) {
        throw new Error(`Failed to fetch projects: ${response.status}`);
      }
      return response.json();
    },
    refetchOnWindowFocus: false,
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ name }: { name: string }) => {
      const response = await authFetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (response.status === 409) {
        throw new Error("A project with this name already exists");
      }
      if (!response.ok) {
        throw new Error(`Failed to create project: ${response.status}`);
      }
      return response.json() as Promise<Project>;
    },
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError(error) {
      toast.error(error.message);
    },
  });
}

export function useRenameProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      projectId,
      name,
    }: {
      projectId: string;
      name: string;
    }) => {
      const response = await authFetch(`/api/projects/${projectId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) {
        throw new Error(`Failed to rename project: ${response.status}`);
      }
    },
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ projectId }: { projectId: string }) => {
      const response = await authFetch(`/api/projects/${projectId}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(`Failed to delete project: ${response.status}`);
      }
    },
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });
}

export function useAssignThreadToProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      projectId,
    }: {
      threadId: string;
      projectId: string | null;
    }) => {
      const response = await authFetch(`/api/threads/${threadId}/project`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId }),
      });
      if (!response.ok) {
        throw new Error(`Failed to assign thread: ${response.status}`);
      }
    },
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}
