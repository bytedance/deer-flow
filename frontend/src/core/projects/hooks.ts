import {
  type InfiniteData,
  type QueryClient,
  type UseInfiniteQueryResult,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";
import { INFINITE_THREADS_QUERY_KEY_PREFIX } from "../threads/hooks";

import {
  archiveProject,
  createProject,
  deleteProject,
  getProject,
  listProjects,
  listProjectThreads,
  patchProject,
  PROJECTS_QUERY_KEY,
  restoreProject,
} from "./api";
import type {
  Project,
  ProjectCreateInput,
  ProjectPatchInput,
  ProjectStatus,
  ProjectThread,
} from "./types";

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
  return useQuery<Project[]>({
    queryKey: [...PROJECTS_QUERY_KEY, { status }],
    queryFn: () => listProjects(status),
    // Static-demo mode has no Gateway; never fire project requests there.
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

export function useProject(id: string) {
  return useQuery<Project>({
    queryKey: [...PROJECTS_QUERY_KEY, "detail", id],
    queryFn: () => getProject(id),
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
  return useInfiniteQuery<
    ProjectThread[],
    Error,
    InfiniteData<ProjectThread[]>,
    readonly unknown[],
    number
  >({
    queryKey: [...PROJECTS_QUERY_KEY, "threads", id],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listProjectThreads(id, {
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
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ProjectCreateInput) => createProject(input),
    onSettled() {
      invalidateProjectCaches(queryClient);
    },
  });
}

export function usePatchProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      input,
    }: {
      projectId: string;
      input: ProjectPatchInput;
    }) => patchProject(projectId, input),
    onSettled() {
      invalidateProjectCaches(queryClient);
    },
  });
}

export function useArchiveProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => archiveProject(projectId),
    onSettled() {
      invalidateProjectCaches(queryClient, { includeThreads: true });
    },
  });
}

export function useRestoreProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => restoreProject(projectId),
    onSettled() {
      invalidateProjectCaches(queryClient, { includeThreads: true });
    },
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => deleteProject(projectId),
    onSettled() {
      invalidateProjectCaches(queryClient, { includeThreads: true });
    },
  });
}
