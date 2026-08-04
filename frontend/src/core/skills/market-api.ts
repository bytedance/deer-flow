import { fetch, getCsrfHeaders } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type MarketSkill = {
  id: string;
  name: string;
  description: string;
  version: string;
  content: string;
  published: boolean;
  installed_version: string | null;
};

export type MarketSkillDraft = Pick<
  MarketSkill,
  "name" | "description" | "version" | "content" | "published"
>;

async function responseOrError(response: Response) {
  if (response.ok) return response.json();
  const data = (await response.json().catch(() => ({}))) as { detail?: string };
  throw new Error(data.detail ?? "技能市场请求失败");
}

export async function loadMarketSkills(admin = false): Promise<MarketSkill[]> {
  const path = admin ? "/api/admin/skill-market" : "/api/skill-market";
  return responseOrError(await fetch(`${getBackendBaseURL()}${path}`));
}

export async function installMarketSkill(
  id: string,
  update = false,
): Promise<MarketSkill> {
  return responseOrError(
    await fetch(`${getBackendBaseURL()}/api/skill-market/${id}/install`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
      body: JSON.stringify({ update }),
    }),
  );
}

export async function uninstallMarketSkill(id: string): Promise<void> {
  await responseOrError(
    await fetch(`${getBackendBaseURL()}/api/skill-market/${id}/install`, {
      method: "DELETE",
      headers: getCsrfHeaders(),
    }),
  );
}

export async function publishMarketSkill(
  draft: MarketSkillDraft,
): Promise<MarketSkill> {
  return responseOrError(
    await fetch(`${getBackendBaseURL()}/api/admin/skill-market`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
      body: JSON.stringify(draft),
    }),
  );
}
