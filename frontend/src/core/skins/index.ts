export {
  DEFAULT_SKIN,
  OBSERVATORY_OPENED_KEY,
  SKIN_IDS,
  SKIN_SCOPED_PREFIXES,
  SKIN_STORAGE_KEY,
  isSkinId,
  type SkinId,
} from "./types";
export { SkinProvider, useSkin } from "./context";
export {
  applySkinToDocument,
  hasPlayedObservatoryOpening,
  markObservatoryOpeningPlayed,
  prefersReducedMotion,
  readStoredSkin,
  writeStoredSkin,
} from "./storage";
