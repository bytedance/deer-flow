import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { Skill } from "./type";

export class SkillRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "SkillRequestError";
    this.status = status;
  }

  get isAdminRequired(): boolean {
    return this.status === 403;
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  const data = (await response.json().catch(() => ({}))) as {
    detail?: string | { message?: string };
  };
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (typeof data.detail?.message === "string") {
    return data.detail.message;
  }
  return `HTTP ${response.status}: ${response.statusText}`;
}

export async function loadSkills() {
  const skills = await fetch(`${getBackendBaseURL()}/api/skills`);
  if (!skills.ok) {
    throw new SkillRequestError(skills.status, await readErrorDetail(skills));
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
    throw new SkillRequestError(
      response.status,
      await readErrorDetail(response),
    );
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
    const message = await readErrorDetail(response);
    // Surface authorization failures so callers can show an admin-only hint
    // instead of a generic failure.
    if (response.status === 403) {
      throw new SkillRequestError(response.status, message);
    }
    // Other HTTP errors keep the existing soft-failure contract.
    return {
      success: false,
      skill_name: "",
      message,
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
    const message = await readErrorDetail(response);
    if (response.status === 403) {
      throw new SkillRequestError(response.status, message);
    }
    return {
      success: false,
      skill_name: "",
      message,
    };
  }

  return response.json();
}
