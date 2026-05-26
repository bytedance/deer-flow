/**
 * Feature Flags
 *
 * Centralized feature flag management for the frontend application.
 * Flags can be toggled via environment variables for quick rollback.
 */

import { env } from "@/env";

/**
 * Check if industrial-first mode is enabled.
 *
 * When enabled (default): Industrial skills are prioritized in UI
 * When disabled: Falls back to generic-first mode (all skills equal)
 *
 * Toggle via NEXT_PUBLIC_INDUSTRIAL_FIRST environment variable:
 * - "true" or "1" = enabled (default)
 * - "false" or "0" = disabled
 */
export function isIndustrialFirstEnabled(): boolean {
  const value = env.NEXT_PUBLIC_INDUSTRIAL_FIRST;

  // Default to enabled if not set
  if (!value) {
    return true;
  }

  // Accept "true" or "1" as enabled
  return value === "true" || value === "1";
}

/**
 * Check if memory UI is enabled.
 */
export function isMemoryUIEnabled(): boolean {
  const value = env.NEXT_PUBLIC_MEMORY_UI_ENABLED;
  return value === "true" || value === "1";
}
