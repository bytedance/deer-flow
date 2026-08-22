import { prefersReducedMotion } from "./storage";

const HORIZON_EVENT = "deerflow:observatory-horizon";

export type HorizonDir = "to-night" | "to-dawn";

let themeTimer: number | undefined;
let fadeTimer: number | undefined;

function clearThemeTimers() {
  if (typeof window === "undefined") return;
  if (themeTimer !== undefined) {
    window.clearTimeout(themeTimer);
    themeTimer = undefined;
  }
  if (fadeTimer !== undefined) {
    window.clearTimeout(fadeTimer);
    fadeTimer = undefined;
  }
}

export function playObservatoryHorizon(dir: HorizonDir) {
  if (typeof window === "undefined") return;
  if (prefersReducedMotion()) return;
  window.dispatchEvent(new CustomEvent(HORIZON_EVENT, { detail: { dir } }));
}

export function subscribeObservatoryHorizon(
  handler: (dir: HorizonDir) => void,
) {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const listener = (event: Event) => {
    const dir = (event as CustomEvent<{ dir?: HorizonDir }>).detail?.dir;
    if (dir === "to-night" || dir === "to-dawn") {
      handler(dir);
    }
  };
  window.addEventListener(HORIZON_EVENT, listener);
  return () => window.removeEventListener(HORIZON_EVENT, listener);
}

export function resolveThemeMode(
  next: "light" | "dark" | "system",
  systemTheme?: string,
): "light" | "dark" {
  if (next === "system") {
    return systemTheme === "dark" ? "dark" : "light";
  }
  return next;
}

export function applyObservatoryTheme(
  next: "light" | "dark" | "system",
  currentResolved: string | undefined,
  setTheme: (value: string) => void,
  systemTheme?: string,
) {
  const resolvedNext = resolveThemeMode(next, systemTheme);
  const resolvedCurrent = currentResolved === "dark" ? "dark" : "light";
  const shouldAnimate =
    typeof document !== "undefined" &&
    document.documentElement.dataset.skin === "observatory" &&
    !prefersReducedMotion() &&
    resolvedNext !== resolvedCurrent;

  clearThemeTimers();
  if (typeof document !== "undefined") {
    document.documentElement.classList.remove("obs-theme-fading");
  }

  if (shouldAnimate) {
    playObservatoryHorizon(resolvedNext === "dark" ? "to-night" : "to-dawn");
    document.documentElement.classList.add("obs-theme-fading");
    themeTimer = window.setTimeout(() => setTheme(next), 900);
    fadeTimer = window.setTimeout(() => {
      document.documentElement.classList.remove("obs-theme-fading");
    }, 2000);
    return;
  }
  setTheme(next);
}
