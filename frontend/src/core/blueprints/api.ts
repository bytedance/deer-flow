import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";

const PREFIX = "/api/blueprints";

async function _gateway<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchGateway(`${getBackendBaseURL()}${path}`, init);
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = res.statusText;
    }
    const err = new Error(
      `Gateway ${init?.method ?? "GET"} ${path} failed: ${res.status}`,
    ) as Error & { status: number; detail: unknown };
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return (await res.json()) as T;
}

export interface BlueprintSummary {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string | null;
  tags: string[];
}

export interface BlueprintDetail extends BlueprintSummary {
  base_dsl: Record<string, unknown>;
  user_configurable: ConfigurableField[];
  recommended_scripts: string[];
  preview_sections: PreviewSection[];
}

export interface ConfigurableField {
  path: string;
  label: string;
  type: string;
  default?: unknown;
  description?: string;
}

export interface PreviewSection {
  id: string;
  title: string;
  component: string;
}

export async function listBlueprints(): Promise<BlueprintSummary[]> {
  return _gateway(PREFIX);
}

export async function getBlueprint(id: string): Promise<BlueprintDetail> {
  return _gateway(`${PREFIX}/${id}`);
}

export async function createTemplateFromBlueprint(
  blueprintId: string,
  body: { name: string; visibility: "private" | "tenant" },
): Promise<{ template_id: string; message: string }> {
  return _gateway(`${PREFIX}/${blueprintId}/create-template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
