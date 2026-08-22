export const SKIN_IDS = ["classic", "observatory"] as const;

export type SkinId = (typeof SKIN_IDS)[number];

export const DEFAULT_SKIN: SkinId = "classic";

export const SKIN_STORAGE_KEY = "deerflow.skin";
export const OBSERVATORY_OPENED_KEY = "deerflow.observatory.opened";

/**
 * Routes that mount `SkinProvider` and may carry the observatory skin. The
 * root-layout boot script and `SkinRouteGuard` use this to keep the observatory
 * palette off public routes (auth, landing, blog, docs).
 */
export const SKIN_SCOPED_PREFIXES = ["/workspace", "/showcase"] as const;

export function isSkinId(value: string | null | undefined): value is SkinId {
  return SKIN_IDS.includes(value as SkinId);
}
