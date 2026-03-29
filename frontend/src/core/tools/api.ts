import { getBackendBaseURL } from "@/core/config";

export interface ConfiguredTool {
  name: string;
  group: string;
  description: string;
}

export interface ConfiguredToolsResponse {
  tools: ConfiguredTool[];
}

export async function loadConfiguredTools() {
  const response = await fetch(`${getBackendBaseURL()}/api/tools`);
  const data = (await response.json()) as ConfiguredToolsResponse;
  return data.tools;
}
