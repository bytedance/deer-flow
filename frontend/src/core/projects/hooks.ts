import {
  type InfiniteData,
  type QueryClient,
  type UseInfiniteQueryResult,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useMemo } from "react";

import { useWorkspaceLifetime } from "@/core/workspaces/context";

import { isStaticWebsiteOnly } from "../static-mode";
import { INFINITE_THREADS_QUERY_KEY_PREFIX } from "../threads/hooks";

import {
  archiveProject,
  attachProjectDocument,
  createProject,
  deleteProject,
  deleteProjectDocument,
  getProject,
  getProjectsConfig,
  listProjectDocuments,
  listProjects,
  listProjectThreadFiles,
  listProjectThreads,
  patchProject,
  PROJECTS_QUERY_KEY,
  promoteThreadFile,
  restoreProject,
  uploadProjectDocument,
  type ProjectRequestOptions,
  type ProjectDocumentListResponse,
  type ProjectDocumentUploadResponse,
  type ProjectsConfig,
  type ProjectThreadFilesResponse,
} from "./api";
import type {
  AttachProjectDocumentResult,
  Project,
  ProjectCreateInput,
  ProjectPatchInput,
  ProjectStatus,
  ProjectThread,
  PromoteThreadFileInput,
} from "./types";

/** Bind requests once; native callers keep their original argument lists. */
function useProjectRequest() {
  const lifetime = useWorkspaceLifetime();
  return useMemo(
    () =>
      lifetime
        ? (signal?: AbortSignal): ProjectRequestOptions => ({
            rest: lifetime.rest,
            signal: signal
              ? AbortSignal.any([lifetime.scope.signal, signal])
              : lifetime.scope.signal,
          })
        : null,
    [lifetime],
  );
}

/**
 * Invalidate project queries. Archive/restore/delete change how member threads
 * group in the sidebar, so those mutations also invalidate the infinite threads
 * search cache via ``includeThreads``.
 */
function invalidateProjectCaches(
  queryClient: QueryClient,
  { includeThreads = false }: { includeThreads?: boolean } = {},
) {
  void queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY });
  if (includeThreads) {
    void queryClient.invalidateQueries({
      queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
    });
  }
}

export function useProjects(
  status?: ProjectStatus,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const request = useProjectRequest();
  return useQuery<Project[]>({
    queryKey: [...PROJECTS_QUERY_KEY, { status }],
    queryFn: ({ signal }) =>
      request ? listProjects(status, request(signal)) : listProjects(status),
    // Static-demo mode has no Gateway; never fire project requests there.
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

/**
 * Server-configured projects limits (``GET /api/projects/config``). Callers
 * fall back to ``PROJECTS_CONFIG_DEFAULT`` while loading or on error — older
 * gateways 404 the endpoint, so ``retry: false`` avoids spending the default
 * retry backoff before the fallback kicks in.
 */
export function useProjectsConfig({
  enabled = true,
}: { enabled?: boolean } = {}) {
  const request = useProjectRequest();
  return useQuery<ProjectsConfig>({
    queryKey: [...PROJECTS_QUERY_KEY, "config"],
    queryFn: ({ signal }) =>
      request ? getProjectsConfig(request(signal)) : getProjectsConfig(),
    retry: false,
    // Config changes only via server redeploy; a stale read is harmless next
    // to the 422 guard of last resort.
    staleTime: 5 * 60_000,
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

export function useProject(id: string) {
  const request = useProjectRequest();
  return useQuery<Project>({
    queryKey: [...PROJECTS_QUERY_KEY, "detail", id],
    queryFn: ({ signal }) =>
      request ? getProject(id, request(signal)) : getProject(id),
    // A deleted or foreign project 404s deterministically and the page has a
    // dedicated not-found state for it; do not spend the default retry
    // backoff (~7s) in "loading" first. Matches useThreadMetadata /
    // useThreadTokenUsage.
    retry: false,
    enabled: !isStaticWebsiteOnly(),
  });
}

export const PROJECT_THREADS_PAGE_SIZE = 100;

/**
 * Project-keyed infinite thread list. Keying the accumulation on the project
 * id fences pagination: an older-page response can only land in the query it
 * was issued for, and a first-page invalidation refetches through TanStack
 * instead of racing manual offset state.
 */
export function useInfiniteProjectThreads(
  id: string,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const request = useProjectRequest();
  return useInfiniteQuery<
    ProjectThread[],
    Error,
    InfiniteData<ProjectThread[]>,
    readonly unknown[],
    number
  >({
    queryKey: [...PROJECTS_QUERY_KEY, "threads", id],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      request
        ? listProjectThreads(
            id,
            {
              limit: PROJECT_THREADS_PAGE_SIZE,
              offset: pageParam,
            },
            request(signal),
          )
        : listProjectThreads(id, {
            limit: PROJECT_THREADS_PAGE_SIZE,
            offset: pageParam,
          }),
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === PROJECT_THREADS_PAGE_SIZE
        ? allPages.reduce((total, page) => total + page.length, 0)
        : undefined,
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

export type ProjectThreadsQueryResult = UseInfiniteQueryResult<
  InfiniteData<ProjectThread[]>,
  Error
>;

export function useCreateProject() {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ProjectCreateInput) =>
      request ? createProject(input, request()) : createProject(input),
    onSettled() {
      if (request?.().signal?.aborted) return;
      invalidateProjectCaches(queryClient);
    },
  });
}

export function usePatchProject() {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      input,
    }: {
      projectId: string;
      input: ProjectPatchInput;
    }) =>
      request
        ? patchProject(projectId, input, request())
        : patchProject(projectId, input),
    onSettled() {
      if (request?.().signal?.aborted) return;
      invalidateProjectCaches(queryClient);
    },
  });
}

export function useArchiveProject() {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      request
        ? archiveProject(projectId, request())
        : archiveProject(projectId),
    onSettled() {
      if (request?.().signal?.aborted) return;
      invalidateProjectCaches(queryClient, { includeThreads: true });
    },
  });
}

export function useRestoreProject() {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      request
        ? restoreProject(projectId, request())
        : restoreProject(projectId),
    onSettled() {
      if (request?.().signal?.aborted) return;
      invalidateProjectCaches(queryClient, { includeThreads: true });
    },
  });
}

export function useDeleteProject() {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) =>
      request ? deleteProject(projectId, request()) : deleteProject(projectId),
    onSettled() {
      if (request?.().signal?.aborted) return;
      invalidateProjectCaches(queryClient, { includeThreads: true });
    },
  });
}

export const PROJECT_DOCUMENTS_PAGE_SIZE = 100;

/**
 * Project-keyed infinite shelf list. The response envelope carries ``total``,
 * so ``hasNextPage`` is exact; the shelf flattens pages and offers a
 * Load-more button (same convention as ``useInfiniteProjectThreads``).
 */
export function useInfiniteProjectDocuments(
  projectId: string,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const request = useProjectRequest();
  return useInfiniteQuery<
    ProjectDocumentListResponse,
    Error,
    InfiniteData<ProjectDocumentListResponse>,
    readonly unknown[],
    number
  >({
    queryKey: [...PROJECTS_QUERY_KEY, "documents", projectId],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      request
        ? listProjectDocuments(
            projectId,
            {
              limit: PROJECT_DOCUMENTS_PAGE_SIZE,
              offset: pageParam,
            },
            request(signal),
          )
        : listProjectDocuments(projectId, {
            limit: PROJECT_DOCUMENTS_PAGE_SIZE,
            offset: pageParam,
          }),
    getNextPageParam: (lastPage) => {
      const loaded = lastPage.offset + lastPage.documents.length;
      return loaded < lastPage.total ? loaded : undefined;
    },
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

/**
 * Project-keyed infinite conversation-files view. The envelope carries the
 * member-thread cursor ``next_offset``, so ``hasNextPage`` comes straight
 * from it; the browser flattens pages and offers a Load-more button (same
 * convention as ``useInfiniteProjectDocuments``). Unlike a manually
 * accumulated page map, every retained page stays subscribed: invalidation
 * or window-focus refetch refreshes them all, so a moved/deleted member
 * thread cannot leave a stale group behind and a shifted page boundary
 * cannot duplicate groups.
 */
export function useInfiniteProjectThreadFiles(
  projectId: string,
  {
    thread_limit,
    file_limit,
  }: { thread_limit?: number; file_limit?: number } = {},
  { enabled = true }: { enabled?: boolean } = {},
) {
  const request = useProjectRequest();
  return useInfiniteQuery<
    ProjectThreadFilesResponse,
    Error,
    InfiniteData<ProjectThreadFilesResponse>,
    readonly unknown[],
    number
  >({
    queryKey: [
      ...PROJECTS_QUERY_KEY,
      "thread-files",
      projectId,
      { thread_limit, file_limit },
    ],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      request
        ? listProjectThreadFiles(
            projectId,
            {
              offset: pageParam,
              thread_limit,
              file_limit,
            },
            request(signal),
          )
        : listProjectThreadFiles(projectId, {
            offset: pageParam,
            thread_limit,
            file_limit,
          }),
    getNextPageParam: (lastPage) => lastPage.next_offset ?? undefined,
    // Static-demo mode has no Gateway; never fire project requests there.
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

export function useUploadProjectDocument(projectId: string) {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation<
    ProjectDocumentUploadResponse,
    Error,
    { file: File; name?: string }
  >({
    mutationFn: (input) =>
      request
        ? uploadProjectDocument(projectId, input, request())
        : uploadProjectDocument(projectId, input),
    onSettled() {
      if (request?.().signal?.aborted) return;
      invalidateProjectCaches(queryClient);
    },
  });
}

export function usePromoteThreadFile(projectId: string) {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation<
    ProjectDocumentUploadResponse,
    Error,
    PromoteThreadFileInput
  >({
    mutationFn: (input) =>
      request
        ? promoteThreadFile(projectId, input, request())
        : promoteThreadFile(projectId, input),
    onSettled() {
      if (request?.().signal?.aborted) return;
      invalidateProjectCaches(queryClient);
    },
  });
}

export function useAttachProjectDocument(projectId: string) {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation<
    AttachProjectDocumentResult,
    Error,
    { documentId: string; threadId: string }
  >({
    mutationFn: ({ documentId, threadId }) =>
      request
        ? attachProjectDocument(projectId, documentId, threadId, request())
        : attachProjectDocument(projectId, documentId, threadId),
    onSettled() {
      if (request?.().signal?.aborted) return;
      // The shelf read does not change, but the target thread's uploads did.
      invalidateProjectCaches(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export function useDeleteProjectDocument(projectId: string) {
  const request = useProjectRequest();
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (documentId) =>
      request
        ? deleteProjectDocument(projectId, documentId, request())
        : deleteProjectDocument(projectId, documentId),
    onSettled() {
      if (request?.().signal?.aborted) return;
      invalidateProjectCaches(queryClient);
    },
  });
}
