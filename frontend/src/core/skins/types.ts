export const SKIN_IDS = ["classic"] as const;

export type SkinId = (typeof SKIN_IDS)[number];

export const DEFAULT_SKIN: SkinId = "classic";

export const SKIN_STORAGE_KEY = "deerflow.skin";

export function isSkinId(value: string | null | undefined): value is SkinId {
  return SKIN_IDS.includes(value as SkinId);
}
