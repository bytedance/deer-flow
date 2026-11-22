import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import { isErrorDetailRecord, readSkillErrorDetail } from "./error-detail";
import type { Skill, SkillLoadDiagnostic } from "./type";

// Keep this in lockstep with `_MAX_SKILL_ARCHIVE_UPLOAD_BYTES` in
// `backend/app/gateway/routers/skills.py`; nginx and Ingress allow 101 MiB so
// multipart framing fits around the same 100 MiB archive limit.
export const MAX_SKILL_ARCHIVE_UPLOAD_BYTES = 100 * 1024 * 1024;

export interface SkillSecurityFinding {
  rule_id: string;
  severity: string;
  file: string | null;
  line: number | null;
  message: string;
  remediation: string | null;
}

export class SkillRequestError extends Error {
  readonly status: number;
  readonly skillName?: string;
  readonly findings: SkillSecurityFinding[];
  readonly code: string | null;
  readonly retryAfter: string | null;

  constructor(
    status: number,
    message: string,
    options: {
      skillName?: string;
      findings?: SkillSecurityFinding[];
      code?: string | null;
      retryAfter?: string | null;
    } = {},
  ) {
    super(message);
    this.name = "SkillRequestError";
    this.status = status;
    this.skillName = options.skillName;
    this.findings = options.findings ?? [];
    this.code = options.code ?? null;
    this.retryAfter = options.retryAfter ?? null;
  }
}

interface SkillErrorDetail {
  message: string;
  skillName?: string;
  findings: SkillSecurityFinding[];
  code: string | null;
  retryAfter: string | null;
}

function parseSecurityFindings(value: unknown): SkillSecurityFinding[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate) => {
    if (typeof candidate !== "object" || candidate === null) return [];
    const finding = candidate as Record<string, unknown>;
    if (
      typeof finding.rule_id !== "string" ||
      typeof finding.severity !== "string" ||
      typeof finding.message !== "string"
    ) {
      return [];
    }
    return [
      {
        rule_id: finding.rule_id,
        severity: finding.severity,
        file: typeof finding.file === "string" ? finding.file : null,
        line: typeof finding.line === "number" ? finding.line : null,
        message: finding.message,
        remediation:
          typeof finding.remediation === "string" ? finding.remediation : null,
      },
    ];
  });
}

export function formatSkillSecurityFindings(
  findings: SkillSecurityFinding[],
): string {
  const lines = findings.slice(0, 3).map((finding) => {
    const location = finding.file
      ? `${finding.file}${finding.line === null ? "" : `:${finding.line}`}`
      : finding.line === null
        ? "archive"
        : `archive:${finding.line}`;
    return `${finding.severity} ${finding.rule_id} · ${location}: ${finding.message}${finding.remediation ? ` ${finding.remediation}` : ""}`;
  });
  const omittedCount = findings.length - lines.length;
  if (omittedCount > 0) {
    lines.push(`... and ${omittedCount} more`);
  }
  return lines.join("\n");
}

async function readErrorDetail(response: Response): Promise<SkillErrorDetail> {
  const detail = await readSkillErrorDetail(response);
  const retryAfter =
    response.status === 429 ? response.headers.get("Retry-After") : null;
  if (typeof detail === "string") {
    return { message: detail, findings: [], code: null, retryAfter };
  }
  if (isErrorDetailRecord(detail) && typeof detail.message === "string") {
    return {
      message: detail.message,
      skillName:
        typeof detail.skill_name === "string" ? detail.skill_name : undefined,
      findings: parseSecurityFindings(detail.findings),
      code: typeof detail.code === "string" ? detail.code : null,
      retryAfter,
    };
  }
  return {
    message: `HTTP ${response.status}${response.statusText ? `: ${response.statusText}` : ""}`,
    findings: [],
    code: null,
    retryAfter,
  };
}

export async function loadSkillDiagnostics(
  signal?: AbortSignal,
): Promise<SkillLoadDiagnostic[]> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/diagnostics/custom`,
    { signal, cache: "no-store" },
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new SkillRequestError(response.status, detail.message, detail);
  }
  const data = (await response.json()) as {
    diagnostics: SkillLoadDiagnostic[];
  };
  return data.diagnostics;
}

export async function reloadSkills(): Promise<void> {
  const response = await fetch(`${getBackendBaseURL()}/api/skills/reload`, {
    method: "POST",
  });
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new SkillRequestError(response.status, detail.message, detail);
  }
}

export async function loadSkills() {
  const skills = await fetch(`${getBackendBaseURL()}/api/skills`);
  if (!skills.ok) {
    const detail = await readErrorDetail(skills);
    throw new SkillRequestError(skills.status, detail.message, detail);
  }
  const json = await skills.json();
  return json.skills as Skill[];
}

export async function enableSkill(
  skillName: string,
  enabled: boolean,
): Promise<Skill> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/${skillName}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        enabled,
      }),
    },
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new SkillRequestError(response.status, detail.message, detail);
  }
  return response.json() as Promise<Skill>;
}

export interface InstallSkillRequest {
  thread_id: string;
  path: string;
}

export interface InstallSkillResponse {
  success: boolean;
  skill_name: string;
  message: string;
  enabled: boolean;
}

export async function installSkill(
  request: InstallSkillRequest,
): Promise<InstallSkillResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/skills/install`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    // Preserve the legacy soft-failure contract except for authorization.
    if (response.status === 403) {
      throw new SkillRequestError(response.status, detail.message, detail);
    }
    return {
      success: false,
      skill_name: "",
      message: detail.message,
      enabled: false,
    };
  }

  return response.json();
}

export async function uploadSkillArchive(
  archive: File,
): Promise<InstallSkillResponse> {
  const formData = new FormData();
  formData.append("archive", archive);

  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/install/upload`,
    {
      method: "POST",
      body: formData,
    },
  );

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    if (
      response.status === 403 ||
      response.status === 413 ||
      detail.findings.length > 0
    ) {
      throw new SkillRequestError(response.status, detail.message, detail);
    }
    return {
      success: false,
      skill_name: "",
      message: detail.message,
      enabled: false,
    };
  }

  return response.json();
}

export interface SkillSourcePreview {
  source: string;
  source_url: string;
  skill_name: string;
  description: string;
  snapshot_digest: string;
  upstream_hash: string | null;
  file_count: number;
  total_bytes: number;
}

export interface InstallSkillSourceRequest {
  source: string;
  expected_snapshot_digest: string;
}

export async function inspectSkillSource(
  source: string,
  signal?: AbortSignal,
): Promise<SkillSourcePreview> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/install/source/inspect`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
      signal,
    },
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new SkillRequestError(response.status, detail.message, detail);
  }
  return response.json() as Promise<SkillSourcePreview>;
}

export async function installSkillSource(
  request: InstallSkillSourceRequest,
  signal?: AbortSignal,
): Promise<InstallSkillResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/install/source`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    },
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new SkillRequestError(response.status, detail.message, detail);
  }
  return response.json() as Promise<InstallSkillResponse>;
}

export interface CustomSkillContent extends Skill {
  content: string;
}

export async function loadCustomSkill(
  skillName: string,
  signal?: AbortSignal,
): Promise<CustomSkillContent> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/custom/${encodeURIComponent(skillName)}`,
    { signal, cache: "no-store" },
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new SkillRequestError(response.status, detail.message, detail);
  }
  return response.json() as Promise<CustomSkillContent>;
}

export async function updateCustomSkill(
  skillName: string,
  content: string,
): Promise<CustomSkillContent> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/custom/${encodeURIComponent(skillName)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new SkillRequestError(response.status, detail.message, detail);
  }
  return response.json() as Promise<CustomSkillContent>;
}

export async function deleteCustomSkill(
  skillName: string,
): Promise<{ success: boolean }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/custom/${encodeURIComponent(skillName)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new SkillRequestError(response.status, detail.message, detail);
  }
  return response.json() as Promise<{ success: boolean }>;
}
