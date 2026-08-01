import { getBackendBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";

import type { AdminModelsResponse, FullModelConfig, ModelsResponse } from "./types";

const STATIC_MODELS_RESPONSE: ModelsResponse = {
  models: [],
  token_usage: { enabled: false },
};

const STATIC_ADMIN_MODELS_RESPONSE: AdminModelsResponse = {
  models: [],
  token_usage: { enabled: false },
};

export async function loadModels(): Promise<ModelsResponse> {
  if (isStaticWebsiteOnly()) {
    return STATIC_MODELS_RESPONSE;
  }

  const res = await fetch(`${getBackendBaseURL()}/api/models`);
  const data = (await res.json()) as Partial<ModelsResponse>;
  return {
    models: data.models ?? [],
    token_usage: data.token_usage ?? { enabled: false },
  };
}

export class ModelsAdminRequestError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ModelsAdminRequestError";
    this.status = status;
  }
  get isAdminRequired(): boolean {
    return this.status === 403;
  }
}

async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  return typeof error.detail === "string" ? error.detail : fallback;
}

export async function loadAdminModels(): Promise<AdminModelsResponse> {
  if (isStaticWebsiteOnly()) {
    return STATIC_ADMIN_MODELS_RESPONSE;
  }

  const res = await fetch(`${getBackendBaseURL()}/api/models/admin`);
  if (!res.ok) {
    throw new ModelsAdminRequestError(
      res.status,
      await readErrorDetail(res, "Failed to load model configurations"),
    );
  }
  return res.json() as Promise<AdminModelsResponse>;
}

export async function updateAdminModels(
  models: FullModelConfig[],
): Promise<AdminModelsResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/models/admin`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ models }),
  });
  if (!res.ok) {
    throw new ModelsAdminRequestError(
      res.status,
      await readErrorDetail(res, "Failed to update model configurations"),
    );
  }
  return res.json() as Promise<AdminModelsResponse>;
}

export async function deleteAdminModel(name: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/models/admin/${encodeURIComponent(name)}`,
    {
      method: "DELETE",
    },
  );
  if (!res.ok) {
    throw new ModelsAdminRequestError(
      res.status,
      await readErrorDetail(res, `Failed to delete model '${name}'`),
    );
  }
}
