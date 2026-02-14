import { getBackendBaseURL } from "../config";

import type { Model } from "./types";

export async function loadModels() {
  const res = fetch(`${getBackendBaseURL()}/api/models`);
  const { models } = (await (await res).json()) as { models: Model[] };
  return models;
}
