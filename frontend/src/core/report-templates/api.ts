import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";

import type {
  CreateTemplateRequest,
  ForkRequest,
  IndexEntry,
  PublishRequest,
  ReportRun,
  ReportTemplate,
  ReportTemplateVersion,
  UpdateTemplateRequest,
  ValidationReport,
  Visibility,
} from "./types";

const PREFIX = "/api/report-templates";
const RUNS_PREFIX = "/api/report-runs";

async function _gateway<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetchGateway(`${getBackendBaseURL()}${path}`, init);
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = res.statusText;
    }
    const err = new Error(
      `Gateway ${init?.method ?? "GET"} ${path} failed: ${res.status} ${JSON.stringify(detail)}`,
    ) as Error & { status: number; detail: unknown };
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Template lifecycle
// ---------------------------------------------------------------------------

export async function listReportTemplates(
  visibility: Visibility = "private",
): Promise<IndexEntry[]> {
  const data = await _gateway<{ templates: IndexEntry[] }>(
    `${PREFIX}?visibility=${visibility}`,
  );
  return data.templates;
}

export async function getReportTemplate(id: string): Promise<{
  template: ReportTemplate;
  scope: Visibility;
}> {
  return _gateway(`${PREFIX}/${id}`);
}

export async function listReportTemplateVersions(
  id: string,
): Promise<number[]> {
  const data = await _gateway<{ versions: number[] }>(
    `${PREFIX}/${id}/versions`,
  );
  return data.versions;
}

export async function getReportTemplateVersion(
  id: string,
  version: number,
): Promise<ReportTemplateVersion> {
  const data = await _gateway<{ version: ReportTemplateVersion }>(
    `${PREFIX}/${id}/versions/${version}`,
  );
  return data.version;
}

export async function createReportTemplate(
  body: CreateTemplateRequest,
): Promise<ReportTemplate> {
  const data = await _gateway<{ template: ReportTemplate }>(PREFIX, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return data.template;
}

export async function updateReportTemplate(
  id: string,
  body: UpdateTemplateRequest,
): Promise<ReportTemplate> {
  const data = await _gateway<{ template: ReportTemplate }>(`${PREFIX}/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return data.template;
}

export async function validateReportTemplate(
  id: string,
  dsl: Record<string, unknown>,
): Promise<ValidationReport> {
  return _gateway(`${PREFIX}/${id}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dsl }),
  });
}

export async function publishReportTemplate(
  id: string,
  body: PublishRequest,
): Promise<ReportTemplate> {
  const data = await _gateway<{ template: ReportTemplate }>(
    `${PREFIX}/${id}/publish`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return data.template;
}

export async function forkReportTemplate(
  id: string,
  body: ForkRequest,
): Promise<ReportTemplate> {
  const data = await _gateway<{ template: ReportTemplate }>(
    `${PREFIX}/${id}/fork`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return data.template;
}

export async function archiveReportTemplate(
  id: string,
  expectedEtag: string,
): Promise<ReportTemplate> {
  const data = await _gateway<{ template: ReportTemplate }>(
    `${PREFIX}/${id}/archive`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_etag: expectedEtag }),
    },
  );
  return data.template;
}

export async function deleteReportTemplate(
  id: string,
  expectedEtag: string,
): Promise<void> {
  await _gateway(
    `${PREFIX}/${id}?expected_etag=${encodeURIComponent(expectedEtag)}`,
    { method: "DELETE" },
  );
}

// ---------------------------------------------------------------------------
// Report runs
// ---------------------------------------------------------------------------

export async function listReportRuns(
  options?: { templateId?: string; limit?: number },
): Promise<ReportRun[]> {
  const params = new URLSearchParams();
  if (options?.templateId) params.set("template_id", options.templateId);
  if (options?.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  const data = await _gateway<{ runs: ReportRun[] }>(
    `${RUNS_PREFIX}${query ? `?${query}` : ""}`,
  );
  return data.runs;
}

export async function getReportRun(id: string): Promise<ReportRun> {
  const data = await _gateway<{ run: ReportRun }>(`${RUNS_PREFIX}/${id}`);
  return data.run;
}

export async function getReportRunPayload(
  id: string,
): Promise<Record<string, unknown>> {
  return _gateway(`${RUNS_PREFIX}/${id}/payload`);
}
