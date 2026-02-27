import { getBackendBaseURL } from "../config";

import type { Model } from "./types";

export async function loadModels() {
  const res = await fetch(`${getBackendBaseURL()}/api/models`);
  const { models } = await res.json();
  return models as Model[];
}
