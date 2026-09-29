import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  LarkAuthCompleteRequest,
  LarkAuthCompleteResponse,
  LarkAuthStartRequest,
  LarkAuthStartResponse,
  LarkConfigCompleteRequest,
  LarkConfigCompleteResponse,
  LarkConfigCredentialsRequest,
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

function normalizeLarkIntegrationStatus(
  status: LarkIntegrationStatus,
): LarkIntegrationStatus {
  // Backends predating the flag omit it entirely; an absent flag means the
  // runtime readiness was not reported as evaluated, so default to false and
  // let the mutation cache preserve the last authoritative runtime fields.
  return {
    ...status,
    sandbox_runtime_probed: status.sandbox_runtime_probed ?? false,
  };
}

export async function loadLarkIntegrationStatus(
  signal?: AbortSignal,
): Promise<LarkIntegrationStatus> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/lark/status`,
    { signal },
  );
  if (!response.ok) {
    throw new LarkIntegrationRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return normalizeLarkIntegrationStatus(await response.json());
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
  const data = (await response.json()) as LarkInstallResponse;
  return { ...data, status: normalizeLarkIntegrationStatus(data.status) };
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
  const data = (await response.json()) as LarkConfigCompleteResponse;
  return { ...data, status: normalizeLarkIntegrationStatus(data.status) };
}

export async function setLarkAppCredentials(
  request: LarkConfigCredentialsRequest,
): Promise<LarkConfigCompleteResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/lark/config/credentials`,
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
  const data = (await response.json()) as LarkConfigCompleteResponse;
  return { ...data, status: normalizeLarkIntegrationStatus(data.status) };
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
  const data = (await response.json()) as LarkAuthCompleteResponse;
  return { ...data, status: normalizeLarkIntegrationStatus(data.status) };
}
