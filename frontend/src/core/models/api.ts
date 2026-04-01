import { getBackendBaseURL } from "../config";

import type { Model } from "./types";

function modelsListUrl() {
  const base = getBackendBaseURL().replace(/\/+$/, "");
  return base ? `${base}/api/models` : "/api/models";
}

export async function loadModels() {
  const res = await fetch(modelsListUrl());
  const bodyText = await res.text();
  if (!res.ok) {
    throw new Error(
      `Models API HTTP ${res.status}: ${bodyText.slice(0, 280)}`.trim(),
    );
  }
  let data: unknown;
  try {
    data = JSON.parse(bodyText) as { models?: Model[] };
  } catch {
    throw new Error(
      "Models API returned non-JSON (is the gateway up on port 8001 / nginx on 2026?)",
    );
  }
  const models = (data as { models?: Model[] }).models;
  if (!Array.isArray(models)) {
    throw new Error("Models API response missing models array");
  }
  return models;
}

/** Triggers LM Studio (or other local loaders) via gateway; no-op for cloud models. */
export async function prepareModel(modelName: string) {
  const res = await fetch(
    `${getBackendBaseURL()}/api/models/${encodeURIComponent(modelName)}/prepare`,
    { method: "POST" },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return (await res.json()) as {
    ok: boolean;
    loaded: boolean;
    model: string | null;
  };
}
