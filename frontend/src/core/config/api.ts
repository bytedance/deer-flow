import { fetchGateway } from "@/core/api";

import { getBackendBaseURL } from "./index";

export interface UIConfig {
  show_bash_script: boolean;
}

export interface AppConfig {
  ui: UIConfig;
}

const DEFAULT_APP_CONFIG: AppConfig = {
  ui: {
    show_bash_script: true,
  },
};

export async function loadAppConfig(): Promise<AppConfig> {
  try {
    const res = await fetchGateway(`${getBackendBaseURL()}/api/config`);
    if (!res.ok) {
      return DEFAULT_APP_CONFIG;
    }
    const data = (await res.json()) as Partial<AppConfig>;
    return {
      ui: {
        show_bash_script: data.ui?.show_bash_script ?? true,
      },
    };
  } catch {
    return DEFAULT_APP_CONFIG;
  }
}
