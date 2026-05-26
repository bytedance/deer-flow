import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";

import type { SkillTier } from "./type";

export async function updateSkillTier(
  skillName: string,
  tier: SkillTier,
): Promise<{ success: boolean; message: string }> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/skills/${skillName}/tier`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ tier }),
    },
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    return {
      success: false,
      message: errorData.detail ?? `HTTP ${response.status}`,
    };
  }

  return { success: true, message: "Tier updated" };
}

export async function batchUpdateSkillTier(
  skillNames: string[],
  tier: SkillTier,
): Promise<{ success: boolean; updated: number; message: string }> {
  const response = await fetchGateway(
    `${getBackendBaseURL()}/api/skills/batch-tier`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ skill_names: skillNames, tier }),
    },
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    return {
      success: false,
      updated: 0,
      message: errorData.detail ?? `HTTP ${response.status}`,
    };
  }

  const data = await response.json();
  return {
    success: true,
    updated: data.updated ?? skillNames.length,
    message: "Batch update complete",
  };
}
