/**
 * Feature Flags
 *
 * Centralized feature flag management for the frontend application.
 * Flags can be toggled via environment variables for quick rollback.
 */

import { env } from "@/env";

/**
 * Check if memory UI is enabled.
 */
export function isMemoryUIEnabled(): boolean {
  const value = env.NEXT_PUBLIC_MEMORY_UI_ENABLED;
  return value === "true" || value === "1";
}
