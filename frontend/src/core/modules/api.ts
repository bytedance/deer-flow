import { getBackendBaseURL } from "@/core/config";

export type ModuleFlags = {
  durable_workflows: {
    enabled: boolean;
    api_enabled: boolean;
    auto_envelope_for_runs: boolean;
  };
};

export async function fetchModuleFlags(): Promise<ModuleFlags> {
  const response = await globalThis.fetch(`${getBackendBaseURL()}/api/modules`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Module flags unavailable (${response.status})`);
  }
  return (await response.json()) as ModuleFlags;
}
