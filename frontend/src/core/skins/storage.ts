import {
  DEFAULT_SKIN,
  SKIN_STORAGE_KEY,
  isSkinId,
  type SkinId,
} from "./types";

export function readStoredSkin(): SkinId {
  if (typeof window === "undefined") {
    return DEFAULT_SKIN;
  }
  try {
    const value = window.localStorage.getItem(SKIN_STORAGE_KEY);
    return isSkinId(value) ? value : DEFAULT_SKIN;
  } catch {
    return DEFAULT_SKIN;
  }
}

export function writeStoredSkin(skin: SkinId) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(SKIN_STORAGE_KEY, skin);
  } catch {
    /* ignore quota / private mode */
  }
}

export function applySkinToDocument(skin: SkinId) {
  if (typeof document === "undefined") {
    return;
  }
  if (skin === DEFAULT_SKIN) {
    delete document.documentElement.dataset.skin;
    return;
  }
  document.documentElement.dataset.skin = skin;
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
