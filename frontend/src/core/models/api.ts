import { apiJson } from "../api/fetch";

import type { Model } from "./types";

export async function loadModels() {
  const { models } = await apiJson<{ models: Model[] }>("/api/models");
  return models;
}
