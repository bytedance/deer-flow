import { z } from "zod";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

const contributions = z.array(
  z.object({
    namespace: z.string(),
    viewer_id: z.string().nullable().optional(),
    module: z.string().nullable(),
    backend_actions: z.array(z.string()).optional(),
    entry: z.string().nullable(),
    // Keep unknown transports so the loader can reject only that contribution.
    transport: z.string().nullable().optional(),
    title: z.string(),
    description: z.string(),
    settings: z.record(z.union([z.boolean(), z.number(), z.string()])),
  }),
);

export const frontendExtensionsQueryKey = ["frontend-extensions"] as const;

export async function fetchFrontendExtensions() {
  const response = await fetch(`${getBackendBaseURL()}/api/plugins`, {
    cache: "no-store",
  });
  if (!response.ok)
    throw new Error(`Frontend extensions unavailable (${response.status})`);
  return contributions.parse(await response.json());
}
