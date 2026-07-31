import { useEffect, useState, type RefObject } from "react";

export type RenderActivityListener = (active: boolean) => void;

/**
 * Reports whether an element is on screen, in a visible document, and allowed
 * to animate by the user's motion preference.
 * Consumers can use this to suspend expensive animation loops.
 */
export function observeRenderActivity(
  element: Element,
  listener: RenderActivityListener,
  initialElementVisible = true,
  respectReducedMotion = true,
) {
  let documentVisible = !document.hidden;
  let elementVisible =
    typeof IntersectionObserver === "undefined" ? true : initialElementVisible;
  const motionPreference =
    !respectReducedMotion || typeof matchMedia === "undefined"
      ? undefined
      : matchMedia("(prefers-reduced-motion: reduce)");
  let reducedMotion = motionPreference?.matches ?? false;
  let lastActive: boolean | undefined;

  const notify = () => {
    const active = documentVisible && elementVisible && !reducedMotion;
    if (active !== lastActive) {
      lastActive = active;
      listener(active);
    }
  };

  const handleVisibilityChange = () => {
    documentVisible = !document.hidden;
    notify();
  };

  document.addEventListener("visibilitychange", handleVisibilityChange);

  const handleMotionPreferenceChange = (event: MediaQueryListEvent) => {
    reducedMotion = event.matches;
    notify();
  };
  motionPreference?.addEventListener("change", handleMotionPreferenceChange);

  const observer =
    typeof IntersectionObserver === "undefined"
      ? undefined
      : new IntersectionObserver(([entry]) => {
          elementVisible = entry?.isIntersecting ?? false;
          notify();
        });
  observer?.observe(element);
  notify();

  return () => {
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    motionPreference?.removeEventListener(
      "change",
      handleMotionPreferenceChange,
    );
    observer?.disconnect();
  };
}

export function useRenderActivity(
  ref: RefObject<Element | null>,
  initialActive = true,
  respectReducedMotion = true,
) {
  // Keep server and first client render aligned; the observer corrects this
  // immediately after mount.
  const [active, setActive] = useState(initialActive);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    return observeRenderActivity(
      element,
      setActive,
      initialActive,
      respectReducedMotion,
    );
  }, [initialActive, ref, respectReducedMotion]);

  return active;
}

export function usePrefersReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    if (typeof matchMedia === "undefined") return;
    const preference = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(preference.matches);
    update();
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);

  return reducedMotion;
}
