import { ApiError, apiFetch, apiJson } from "@/core/api/fetch";

import type { Skill } from "./type";

export async function loadSkills() {
  const json = await apiJson<{ skills: Skill[] }>("/api/skills");
  return json.skills;
}

export async function enableSkill(skillName: string, enabled: boolean) {
  const res = await apiFetch(`/api/skills/${skillName}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return res.json();
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
  try {
    return await apiJson<InstallSkillResponse>("/api/skills/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  } catch (error) {
    const message =
      error instanceof ApiError
        ? (error.detail ?? error.message)
        : "Failed to install skill";
    return { success: false, skill_name: "", message };
  }
}
