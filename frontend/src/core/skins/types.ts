export const SKIN_IDS = ["classic", "observatory"] as const;

export type SkinId = (typeof SKIN_IDS)[number];

export const DEFAULT_SKIN: SkinId = "classic";

export const SKIN_STORAGE_KEY = "deerflow.skin";
export const OBSERVATORY_OPENED_KEY = "deerflow.observatory.opened";

export function isSkinId(value: string | null | undefined): value is SkinId {
  return SKIN_IDS.includes(value as SkinId);
}
