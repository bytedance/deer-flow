import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface SkillExportNotice {
  code: string;
  message: string;
  path?: string;
}
export interface SkillExportManifest {
  skill_name: string;
  revision: string | null;
  can_export: boolean;
  file_count: number;
  directory_count: number;
  total_bytes: number;
  files: {
    path: string;
    type: "file" | "directory";
    size: number;
    executable: boolean;
  }[];
  requirements: {
    compatibility: string | null;
    allowed_tools: string[] | null;
    required_secrets: { name: string; optional: boolean }[] | null;
  };
  warnings: SkillExportNotice[];
  blockers: SkillExportNotice[];
}
export class SkillExportRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "SkillExportRequestError";
  }
}
async function exportRequest(
  path: string,
  signal: AbortSignal,
): Promise<Response> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/custom/${path}`,
    { signal, cache: "no-store" },
  );
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as {
      detail?: { code?: string; message?: string } | string;
    };
    const detail = data.detail;
    throw new SkillExportRequestError(
      response.status,
      typeof detail === "object"
        ? (detail.code ?? "skill_export_failed")
        : "skill_export_failed",
      typeof detail === "string"
        ? detail
        : (detail?.message ?? "Could not export this skill."),
    );
  }
  return response;
}
export async function loadSkillExportManifest(
  name: string,
  signal: AbortSignal,
): Promise<SkillExportManifest> {
  const response = await exportRequest(
    `${encodeURIComponent(name)}/export-manifest`,
    signal,
  );
  return response.json() as Promise<SkillExportManifest>;
}
export async function downloadSkillExport(
  name: string,
  revision: string,
  signal: AbortSignal,
): Promise<Blob> {
  const response = await exportRequest(
    `${encodeURIComponent(name)}/export?expected_revision=${encodeURIComponent(revision)}`,
    signal,
  );
  if (
    response.headers.get("content-type")?.split(";")[0] !== "application/zip"
  ) {
    throw new SkillExportRequestError(
      502,
      "skill_export_failed",
      "The server did not return a skill archive.",
    );
  }
  return response.blob();
}

export function handOffSkillDownload(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${name}.skill`;
  try {
    document.body.append(link);
    link.click();
  } finally {
    link.remove();
    // Allow the browser to consume the URL before releasing it, even if the
    // dialog unmounts as soon as download is handed off.
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }
}
