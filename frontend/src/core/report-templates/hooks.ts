import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  archiveReportTemplate,
  createReportTemplate,
  deleteReportTemplate,
  forkReportTemplate,
  getReportRun,
  getReportRunPayload,
  getReportTemplate,
  getReportTemplateVersion,
  listReportRuns,
  listReportTemplateVersions,
  listReportTemplates,
  publishReportTemplate,
  updateReportTemplate,
  validateReportTemplate,
} from "./api";
import type {
  CreateTemplateRequest,
  ForkRequest,
  PublishRequest,
  UpdateTemplateRequest,
  Visibility,
} from "./types";

const TEMPLATES_KEY = "report-templates" as const;
const RUNS_KEY = "report-runs" as const;

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

export function useReportTemplates(visibility: Visibility = "private") {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: [TEMPLATES_KEY, "list", visibility],
    queryFn: () => listReportTemplates(visibility),
  });
  return {
    templates: data ?? [],
    isLoading,
    error,
    refetch,
  };
}

export function useReportTemplate(id: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: [TEMPLATES_KEY, "one", id],
    queryFn: () => getReportTemplate(id ?? ""),
    enabled: !!id,
  });
  return { detail: data, isLoading, error };
}

export function useReportTemplateVersions(id: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: [TEMPLATES_KEY, "versions", id],
    queryFn: () => listReportTemplateVersions(id ?? ""),
    enabled: !!id,
  });
  return { versions: data ?? [], isLoading, error };
}

export function useReportTemplateVersion(
  id: string | null,
  version: number | null,
) {
  const { data, isLoading, error } = useQuery({
    queryKey: [TEMPLATES_KEY, "version", id, version],
    queryFn: () => getReportTemplateVersion(id ?? "", version ?? 0),
    enabled: !!id && version != null,
  });
  return { snapshot: data, isLoading, error };
}

export function useCreateReportTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateTemplateRequest) => createReportTemplate(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

export function useUpdateReportTemplate(templateId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UpdateTemplateRequest) =>
      updateReportTemplate(templateId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

export function useValidateReportTemplate(templateId: string) {
  return useMutation({
    mutationFn: (dsl: Record<string, unknown>) =>
      validateReportTemplate(templateId, dsl),
  });
}

export function usePublishReportTemplate(templateId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PublishRequest) =>
      publishReportTemplate(templateId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

export function useForkReportTemplate(templateId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ForkRequest) => forkReportTemplate(templateId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

export function useArchiveReportTemplate(templateId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (expectedEtag: string) =>
      archiveReportTemplate(templateId, expectedEtag),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

export function useDeleteReportTemplate(templateId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (expectedEtag: string) =>
      deleteReportTemplate(templateId, expectedEtag),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [TEMPLATES_KEY] });
    },
  });
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export function useReportRuns(options?: {
  templateId?: string;
  limit?: number;
}) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: [RUNS_KEY, "list", options?.templateId, options?.limit],
    queryFn: () => listReportRuns(options),
  });
  return { runs: data ?? [], isLoading, error, refetch };
}

export function useReportRun(id: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: [RUNS_KEY, "one", id],
    queryFn: () => getReportRun(id ?? ""),
    enabled: !!id,
  });
  return { run: data, isLoading, error };
}

export function useReportRunPayload(id: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: [RUNS_KEY, "payload", id],
    queryFn: () => getReportRunPayload(id ?? ""),
    enabled: !!id,
  });
  return { payload: data, isLoading, error };
}
