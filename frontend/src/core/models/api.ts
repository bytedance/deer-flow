import { getBackendBaseURL } from "../config";

import type {
  DetectModelsResponse,
  Model,
  ModelsResponse,
  ModelUpsertPayload,
} from "./types";

export async function loadModels(): Promise<ModelsResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/models`);
  const data = (await res.json()) as Partial<ModelsResponse>;
  return {
    models: data.models ?? [],
    token_usage: data.token_usage ?? { enabled: false },
  };
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const data = (await response.json()) as T & { detail?: string };
  if (!response.ok) {
    throw new Error(data.detail ?? response.statusText);
  }
  return data;
}

export async function detectModels({
  baseUrl,
  apiKey,
}: {
  baseUrl: string;
  apiKey?: string;
}): Promise<DetectModelsResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/models/detect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_url: baseUrl, api_key: apiKey ?? null }),
  });
  return parseJsonResponse<DetectModelsResponse>(response);
}

export async function createModel(payload: ModelUpsertPayload): Promise<Model> {
  const response = await fetch(`${getBackendBaseURL()}/api/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse<Model>(response);
}

export async function updateModel({
  name,
  payload,
}: {
  name: string;
  payload: ModelUpsertPayload;
}): Promise<Model> {
  const response = await fetch(`${getBackendBaseURL()}/api/models/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse<Model>(response);
}

export async function deleteModel(name: string): Promise<void> {
  const response = await fetch(`${getBackendBaseURL()}/api/models/${name}`, {
    method: "DELETE",
  });
  await parseJsonResponse(response);
}
