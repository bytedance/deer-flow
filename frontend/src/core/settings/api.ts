import { z } from "zod";

import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import {
  persistedUserSettingsSchema,
  type PersistedUserSettings,
  type PersistedUserSettingsPatch,
} from "./persistence";

const responseSchema = z
  .object({
    settings: persistedUserSettingsSchema.nullable(),
    revision: z.number().int().nonnegative(),
  })
  .strict();

export type UserSettingsResponse = z.infer<typeof responseSchema>;
const EXPECTED_USER_ID_HEADER = "X-DeerFlow-Expected-User-Id";

function url(): string {
  return `${getBackendBaseURL()}/api/user-preferences`;
}

async function parseResponse(
  response: Response,
): Promise<UserSettingsResponse> {
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to synchronize user settings: ${response.statusText}`,
    );
  }
  return responseSchema.parse(await response.json());
}

export async function fetchUserSettings(
  expectedUserId: string,
): Promise<UserSettingsResponse> {
  return parseResponse(
    await fetch(url(), {
      headers: { [EXPECTED_USER_ID_HEADER]: expectedUserId },
    }),
  );
}

export async function initializeUserSettings(
  expectedUserId: string,
  settings: PersistedUserSettings,
): Promise<UserSettingsResponse> {
  return parseResponse(
    await fetch(url(), {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        [EXPECTED_USER_ID_HEADER]: expectedUserId,
      },
      body: JSON.stringify({ settings }),
    }),
  );
}

export async function patchUserSettings(
  expectedUserId: string,
  patch: PersistedUserSettingsPatch,
): Promise<UserSettingsResponse> {
  return parseResponse(
    await fetch(url(), {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        [EXPECTED_USER_ID_HEADER]: expectedUserId,
      },
      body: JSON.stringify(patch),
    }),
  );
}
