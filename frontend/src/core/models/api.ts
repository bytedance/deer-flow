import { getBackendBaseURL } from "../config";
import { env } from "@/env";

import type { Model } from "./types";

export async function loadModels() {
  const url =
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
      ? `${window.location.origin}/mock/api/models`
      : `${getBackendBaseURL()}/api/models`;
  const res = await fetch(url);
  const { models } = (await res.json()) as { models: Model[] };
  return models;
}
