import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { Skill } from "./type";

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

  constructor(
    status: number,
    message: string,
    options: {
      skillName?: string;
      findings?: SkillSecurityFinding[];
    } = {},
  ) {
    super(message);
    this.name = "SkillRequestError";
    this.status = status;
    this.skillName = options.skillName;
    this.findings = options.findings ?? [];
  }

  get isAdminRequired(): boolean {
    return this.status === 403;
  }
}

interface SkillErrorDetail {
  message: string;
  skillName?: string;
  findings: SkillSecurityFinding[];
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
  const data = (await response.json().catch(() => ({}))) as {
    detail?:
      | string
      | {
          message?: unknown;
          skill_name?: unknown;
          findings?: unknown;
        };
  };
  if (typeof data.detail === "string") {
    return { message: data.detail, findings: [] };
  }
  if (typeof data.detail?.message === "string") {
    return {
      message: data.detail.message,
      skillName:
        typeof data.detail.skill_name === "string"
          ? data.detail.skill_name
          : undefined,
      findings: parseSecurityFindings(data.detail.findings),
    };
  }
  return {
    message: `HTTP ${response.status}${response.statusText ? `: ${response.statusText}` : ""}`,
    findings: [],
  };
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

export async function enableSkill(skillName: string, enabled: boolean) {
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
  return response.json();
}

export interface InstallSkillRequest {
  thread_id: string;
  path: string;
}

export interface InstallSkillResponse {
  success: boolean;
  skill_name: string;
  message: string;
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
    // Surface authorization failures so callers can show an admin-only hint
    // instead of a generic failure.
    if (response.status === 403) {
      throw new SkillRequestError(response.status, detail.message, detail);
    }
    // Other HTTP errors keep the existing soft-failure contract.
    return {
      success: false,
      skill_name: "",
      message: detail.message,
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
    };
  }

  return response.json();
}
