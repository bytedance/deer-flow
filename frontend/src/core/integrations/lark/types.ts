export interface LarkCliProbe {
  available: boolean;
  path: string | null;
  version: string | null;
  error: string | null;
}

export interface LarkAuthProbe {
  status:
    | "authenticated"
    | "not_authorized"
    | "not_configured"
    | "unavailable"
    | "error";
  message: string | null;
  user: string | null;
  verified: boolean;
}

export type LarkSandboxRuntimeMode =
  | "none"
  | "gateway-download"
  | "init-container";

export interface LarkIntegrationStatus {
  installed: boolean;
  version: string;
  manifest_version: string | null;
  latest_available_version: string | null;
  runtime_version_mismatch: boolean;
  app_configured: boolean;
  app_id: string | null;
  app_brand: string | null;
  skills_expected: number;
  skills_installed: number;
  installed_skills: string[];
  enabled_skills: string[];
  install_path: string;
  cli: LarkCliProbe;
  auth: LarkAuthProbe;
  sandbox_runtime_mode: LarkSandboxRuntimeMode;
  sandbox_runtime_ready: boolean;
  sandbox_runtime_detail: string | null;
}

export interface LarkInstallResponse {
  success: boolean;
  installed_skills: string[];
  message: string;
  status: LarkIntegrationStatus;
}

export interface LarkAuthStartRequest {
  recommend?: boolean;
  domains?: string[];
  scope?: string | null;
}

export interface LarkAuthStartResponse {
  verification_url: string;
  device_code: string;
  expires_in: number | null;
  user_code: string | null;
  hint: string | null;
}

export interface LarkConfigStartRequest {
  brand?: "feishu" | "lark";
}

export interface LarkConfigStartResponse {
  verification_url: string;
  device_code: string;
  expires_in: number | null;
  interval: number | null;
  user_code: string | null;
  brand: "feishu" | "lark";
}

export interface LarkConfigCompleteRequest {
  device_code: string;
  brand: "feishu" | "lark";
  interval: number | null;
  expires_in: number | null;
}

export interface LarkConfigCompleteResponse {
  success: boolean;
  message: string;
  status: LarkIntegrationStatus;
}

export interface LarkAuthCompleteRequest {
  device_code: string;
  wait_timeout_seconds?: number;
}

export interface LarkAuthCompleteResponse {
  success: boolean;
  message: string;
  status: LarkIntegrationStatus;
}
