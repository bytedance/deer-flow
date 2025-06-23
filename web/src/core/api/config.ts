import { type DeerFlowConfig } from "../config/types";

import { resolveServiceURL } from "./resolve-service-url";

declare global {
  interface Window {
    __deerflowConfig: DeerFlowConfig;
  }
}

export async function loadConfig(): Promise<DeerFlowConfig> {
  try {
    const res = await fetch(resolveServiceURL("./config"));
    if (!res.ok) {
      console.warn(`Failed to fetch config, status: ${res.status}. Using default config.`);
      // Return a default config if the fetch was not successful (e.g. 404, 500)
      return getDefaultConfig();
    }
    const config = await res.json();
    return config;
  } catch (error) {
    console.warn("Error fetching config:", error, "Using default config.");
    // Return a default config if the fetch itself fails (e.g. network error)
    return getDefaultConfig();
  }
}

function getDefaultConfig(): DeerFlowConfig {
  return {
    rag: {
      provider: "default", // Or some other sensible default
    },
    models: {
      basic: ["default-basic-model"], // Or empty array
      reasoning: ["default-reasoning-model"], // Or empty array
    },
  };
}

export function getConfig(): DeerFlowConfig {
  if (
    typeof window === "undefined" ||
    typeof window.__deerflowConfig === "undefined"
  ) {
    throw new Error("Config not loaded");
  }
  return window.__deerflowConfig;
}
