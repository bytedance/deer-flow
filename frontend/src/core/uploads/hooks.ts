/**
 * React hooks for file uploads
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { useWorkspaceLifetime } from "@/core/workspaces/context";

import {
  deleteUploadedFile,
  getUploadLimits,
  listUploadedFiles,
  uploadFiles,
  type UploadedFileInfo,
  type UploadResponse,
} from "./api";

/**
 * Hook to load the gateway-enforced upload limits.
 * Callers intentionally degrade to server-side validation if this request fails.
 */
export function useUploadLimits(threadId: string) {
  const lifetime = useWorkspaceLifetime();
  return useQuery({
    queryKey: ["uploads", "limits", threadId],
    queryFn: ({ signal }) =>
      lifetime
        ? getUploadLimits(threadId, { rest: lifetime.rest, signal })
        : getUploadLimits(threadId),
    enabled: !!threadId,
    retry: false,
    staleTime: 60_000,
  });
}

/**
 * Hook to upload files
 */
export function useUploadFiles(threadId: string) {
  const lifetime = useWorkspaceLifetime();
  const queryClient = useQueryClient();

  return useMutation<UploadResponse, Error, File[]>({
    mutationFn: (files: File[]) =>
      lifetime
        ? uploadFiles(threadId, files, { rest: lifetime.rest })
        : uploadFiles(threadId, files),
    onSuccess: () => {
      if (lifetime?.scope.signal.aborted) return;
      // Invalidate the uploaded files list
      void queryClient.invalidateQueries({
        queryKey: ["uploads", "list", threadId],
      });
    },
  });
}

/**
 * Hook to list uploaded files
 */
export function useUploadedFiles(threadId: string) {
  const lifetime = useWorkspaceLifetime();
  return useQuery({
    queryKey: ["uploads", "list", threadId],
    queryFn: ({ signal }) =>
      lifetime
        ? listUploadedFiles(threadId, { rest: lifetime.rest, signal })
        : listUploadedFiles(threadId),
    enabled: !!threadId,
  });
}

/**
 * Hook to delete an uploaded file
 */
export function useDeleteUploadedFile(threadId: string) {
  const lifetime = useWorkspaceLifetime();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (filename: string) =>
      lifetime
        ? deleteUploadedFile(threadId, filename, { rest: lifetime.rest })
        : deleteUploadedFile(threadId, filename),
    onSuccess: () => {
      if (lifetime?.scope.signal.aborted) return;
      // Invalidate the uploaded files list
      void queryClient.invalidateQueries({
        queryKey: ["uploads", "list", threadId],
      });
    },
  });
}

/**
 * Hook to handle file uploads in submit flow
 * Returns a function that uploads files and returns their info
 */
export function useUploadFilesOnSubmit(threadId: string) {
  const lifetime = useWorkspaceLifetime();
  const uploadMutation = useUploadFiles(threadId);

  return useCallback(
    async (files: File[]): Promise<UploadedFileInfo[]> => {
      lifetime?.scope.signal.throwIfAborted();
      if (files.length === 0) {
        return [];
      }

      const result = await uploadMutation.mutateAsync(files);
      lifetime?.scope.signal.throwIfAborted();
      return result.files;
    },
    [uploadMutation, lifetime],
  );
}
