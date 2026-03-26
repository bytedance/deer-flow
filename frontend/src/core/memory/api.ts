import { getBackendBaseURL } from "../config";

import type { UserMemory } from "./types";

export async function loadMemory() {
  const response = await fetch(`${getBackendBaseURL()}/api/memory`);
  const body = await response.text();

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    const trimmed = body.trim();
    if (trimmed) {
      try {
        const errorData = JSON.parse(trimmed) as {
          detail?: unknown;
          message?: unknown;
        };
        if (typeof errorData.detail === "string" && errorData.detail.trim()) {
          detail = errorData.detail.trim();
        } else if (
          typeof errorData.message === "string" &&
          errorData.message.trim()
        ) {
          detail = errorData.message.trim();
        } else {
          detail = trimmed;
        }
      } catch {
        detail = trimmed;
      }
    }
    throw new Error(`Failed to load memory: ${detail}`);
  }

  const trimmed = body.trim();
  if (!trimmed) {
    throw new Error("Failed to load memory: empty response");
  }

  try {
    return JSON.parse(trimmed) as UserMemory;
  } catch {
    throw new Error("Failed to load memory: invalid JSON response");
  }
}
