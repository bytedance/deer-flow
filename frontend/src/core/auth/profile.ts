import { z } from "zod";

import { fetch } from "@/core/api/fetcher";

import { parseAuthError } from "./types";

const profileSchema = z.object({ nickname: z.string().nullable() });
export type AccountProfile = z.infer<typeof profileSchema>;

export async function accountProfile(
  nickname?: string,
): Promise<AccountProfile> {
  const response = await fetch("/api/v1/auth/profile", {
    method: nickname === undefined ? "GET" : "PATCH",
    ...(nickname === undefined
      ? {}
      : {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ nickname }),
        }),
  });
  if (!response.ok)
    throw new Error(parseAuthError(await response.json()).message);
  return profileSchema.parse(await response.json());
}
