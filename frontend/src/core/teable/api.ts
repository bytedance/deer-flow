import { getBackendBaseURL } from "@/core/config";

import type {
  TeableBase,
  TeableConfig,
  TeableShareView,
  TeableSpace,
  TeableTable,
} from "./types";

export async function fetchTeableSpaces(): Promise<TeableSpace[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/teable/spaces`);
  if (!res.ok) throw new Error(`Failed to load spaces: ${res.statusText}`);
  const data = (await res.json()) as { spaces: TeableSpace[] };
  return data.spaces;
}

export async function fetchTeableBases(spaceId: string): Promise<TeableBase[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/teable/spaces/${encodeURIComponent(spaceId)}/bases`,
  );
  if (!res.ok) throw new Error(`Failed to load bases: ${res.statusText}`);
  const data = (await res.json()) as { bases: TeableBase[] };
  return data.bases;
}

export async function fetchTeableConfig(): Promise<TeableConfig> {
  const res = await fetch(`${getBackendBaseURL()}/api/teable/config`);
  if (!res.ok)
    throw new Error(`Failed to load Teable config: ${res.statusText}`);
  return res.json() as Promise<TeableConfig>;
}

export async function fetchTeableTables(
  baseId: string,
): Promise<TeableTable[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/teable/bases/${encodeURIComponent(baseId)}/tables`,
  );
  if (!res.ok) throw new Error(`Failed to load tables: ${res.statusText}`);
  const data = (await res.json()) as { tables: TeableTable[] };
  return data.tables;
}

export async function fetchTeableShareView(
  tableId: string,
  viewType = "grid",
): Promise<TeableShareView> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/teable/tables/${encodeURIComponent(tableId)}/share-view?view_type=${encodeURIComponent(viewType)}`,
  );
  if (!res.ok)
    throw new Error(`Failed to create share view: ${res.statusText}`);
  return res.json() as Promise<TeableShareView>;
}

export async function ensureTeableAgent(): Promise<{
  status: string;
  agent_name: string;
}> {
  const res = await fetch(`${getBackendBaseURL()}/api/teable/ensure-agent`, {
    method: "POST",
  });
  if (!res.ok)
    throw new Error(`Failed to ensure teable agent: ${res.statusText}`);
  return res.json() as Promise<{ status: string; agent_name: string }>;
}
