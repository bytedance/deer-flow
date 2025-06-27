import { type DeerFlowConfig } from "../config/types";

import { resolveServiceURL } from "./resolve-service-url";

declare global {
  interface Window {
    __deerflowConfig: DeerFlowConfig;
  }
}

export async function loadConfig() {
  const res = await fetch(resolveServiceURL("./config"));
  const config = await res.json();
  return config;
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
