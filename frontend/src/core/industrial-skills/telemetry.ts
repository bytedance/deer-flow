/**
 * Industrial Skills Telemetry
 *
 * Tracks usage metrics for industrial vs foundation skills,
 * onboarding completion rates, and skill tier distribution.
 */

type TelemetryEventType =
  | "skill_invocation"
  | "onboarding_complete"
  | "onboarding_skip"
  | "tier_change"
  | "batch_tier_change";

interface TelemetryEvent {
  type: TelemetryEventType;
  skill_name?: string;
  skill_tier?: "core-industrial" | "foundation";
  user_id?: string;
  tenant_id?: string;
  from_tier?: string;
  to_tier?: string;
  count?: number;
  timestamp: number;
}

const EVENT_BUFFER: TelemetryEvent[] = [];
const FLUSH_INTERVAL_MS = 15000; // 15 seconds
const MAX_BUFFER_SIZE = 100;

let flushTimer: ReturnType<typeof setInterval> | null = null;

function getBackendBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

function startFlushTimer(): void {
  if (flushTimer) return;
  flushTimer = setInterval(() => {
    void flushEvents();
  }, FLUSH_INTERVAL_MS);
}

async function flushEvents(): Promise<void> {
  if (EVENT_BUFFER.length === 0) return;

  const events = EVENT_BUFFER.splice(0, EVENT_BUFFER.length);
  const baseUrl = getBackendBaseUrl();

  try {
    await fetch(`${baseUrl}/api/telemetry/industrial-skills`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    });
  } catch (error) {
    // Silently fail - don't disrupt user experience
    console.error("Failed to flush industrial skills telemetry:", error);
  }
}

function enqueue(event: Omit<TelemetryEvent, "timestamp">): void {
  EVENT_BUFFER.push({ ...event, timestamp: Date.now() });

  if (EVENT_BUFFER.length >= MAX_BUFFER_SIZE) {
    void flushEvents();
  } else {
    startFlushTimer();
  }
}

/**
 * Track skill invocation
 */
export function trackSkillInvocation(
  skillName: string,
  skillTier: "core-industrial" | "foundation",
  userId?: string,
  tenantId?: string
): void {
  enqueue({
    type: "skill_invocation",
    skill_name: skillName,
    skill_tier: skillTier,
    user_id: userId,
    tenant_id: tenantId,
  });
}

/**
 * Track onboarding completion
 */
export function trackOnboardingComplete(
  userId?: string,
  tenantId?: string
): void {
  enqueue({
    type: "onboarding_complete",
    user_id: userId,
    tenant_id: tenantId,
  });
}

/**
 * Track onboarding skip
 */
export function trackOnboardingSkip(
  userId?: string,
  tenantId?: string
): void {
  enqueue({
    type: "onboarding_skip",
    user_id: userId,
    tenant_id: tenantId,
  });
}

/**
 * Track tier change (admin action)
 */
export function trackTierChange(
  skillName: string,
  fromTier: string,
  toTier: string,
  userId?: string,
  tenantId?: string
): void {
  enqueue({
    type: "tier_change",
    skill_name: skillName,
    from_tier: fromTier,
    to_tier: toTier,
    user_id: userId,
    tenant_id: tenantId,
  });
}

/**
 * Track batch tier change (admin action)
 */
export function trackBatchTierChange(
  count: number,
  toTier: string,
  userId?: string,
  tenantId?: string
): void {
  enqueue({
    type: "batch_tier_change",
    count,
    to_tier: toTier,
    user_id: userId,
    tenant_id: tenantId,
  });
}

/**
 * Flush any pending events immediately
 */
export async function flushTelemetry(): Promise<void> {
  await flushEvents();
}
