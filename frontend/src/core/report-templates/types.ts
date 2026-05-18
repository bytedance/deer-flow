// Phase 5 — Report Template platform TypeScript surface

export type Visibility = "private" | "tenant" | "builtin";
export type TemplateStatus = "draft" | "published" | "archived";

export interface IndexEntry {
  id: string;
  name: string;
  display_name: string;
  visibility: Visibility;
  status: TemplateStatus;
  current_version: number;
  tags: string[];
  updated_at: string;
}

export interface ReportTemplate {
  id: string;
  name: string;
  display_name: string;
  description: string;
  owner_user_id: string;
  tenant_id: string;
  visibility: Visibility;
  status: TemplateStatus;
  current_version: number;
  dsl_version: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  etag: string;
}

export interface ReportTemplateVersion {
  template_id: string;
  version: number;
  dsl: Record<string, unknown>;
  dsl_yaml: string;
  checksum: string;
  source_template_id: string | null;
  source_template_version: number | null;
  created_by: string;
  created_at: string;
  changelog: string;
}

export interface ValidationIssue {
  code: string;
  path: string;
  message: string;
  severity: "error" | "warning";
}

export interface ValidationReport {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export type RunStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled";

export interface ReportRun {
  id: string;
  template_id: string;
  template_version: number | null;
  template_version_ref: string | null;
  thread_id: string;
  run_id: string;
  user_id: string;
  tenant_id: string;
  idempotency_key: string | null;
  status: RunStatus;
  parameters_summary: Record<string, unknown>;
  parameters_path: string | null;
  report_payload_path: string | null;
  artifact_paths: Record<string, string | null>;
  pdf_skipped_reason: string | null;
  data_snapshot_paths: string[];
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

// ---- Request payloads ----

export interface CreateTemplateRequest {
  name: string;
  display_name: string;
  description?: string;
  visibility?: Visibility;
  tags?: string[];
  dsl: Record<string, unknown>;
  dsl_yaml: string;
}

export interface UpdateTemplateRequest {
  display_name?: string;
  description?: string;
  tags?: string[];
  dsl: Record<string, unknown>;
  dsl_yaml: string;
  expected_etag: string;
}

export interface PublishRequest {
  expected_current_version: number;
  changelog?: string;
}

export interface ForkRequest {
  source_version: number;
  new_name: string;
  new_display_name: string;
}
