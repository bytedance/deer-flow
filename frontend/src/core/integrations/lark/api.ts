import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  LarkAuthCompleteRequest,
  LarkAuthCompleteResponse,
  LarkAuthStartRequest,
  LarkAuthStartResponse,
  LarkConfigCompleteRequest,
  LarkConfigCompleteResponse,
  LarkConfigStartRequest,
  LarkConfigStartResponse,
  LarkInstallResponse,
  LarkIntegrationStatus,
} from "./types";

export class LarkIntegrationRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "LarkIntegrationRequestError";
    this.status = status;
  }

  get isAdminRequired(): boolean {
    return this.status === 403;
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  const data = (await response.json().catch(() => ({}))) as {
    detail?: string;
  };
  return data.detail ?? `HTTP ${response.status}: ${response.statusText}`;
}

export async function loadLarkIntegrationStatus(): Promise<LarkIntegrationStatus> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/lark/status`,
  );
  if (!response.ok) {
    throw new LarkIntegrationRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return response.json();
}

export async function installLarkIntegration(): Promise<LarkInstallResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/lark/install`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    throw new LarkIntegrationRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return response.json();
}

export async function startLarkAuthorization(
  request: LarkAuthStartRequest = {},
): Promise<LarkAuthStartResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/lark/auth/start`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    throw new LarkIntegrationRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return response.json();
}

export async function startLarkConfiguration(
  request: LarkConfigStartRequest = {},
): Promise<LarkConfigStartResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/lark/config/start`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    throw new LarkIntegrationRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return response.json();
}

export async function completeLarkConfiguration(
  request: LarkConfigCompleteRequest,
): Promise<LarkConfigCompleteResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/lark/config/complete`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    throw new LarkIntegrationRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return response.json();
}

export async function completeLarkAuthorization(
  request: LarkAuthCompleteRequest,
): Promise<LarkAuthCompleteResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/lark/auth/complete`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    throw new LarkIntegrationRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return response.json();
}
