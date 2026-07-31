import { useEffect, useState, type RefObject } from "react";

export type RenderActivityListener = (active: boolean) => void;

/**
 * Reports whether an element is both on screen and in a visible document.
 * Consumers can use this to suspend expensive animation loops.
 */
export function observeRenderActivity(
  element: Element,
  listener: RenderActivityListener,
  initialElementVisible = true,
) {
  let documentVisible = !document.hidden;
  let elementVisible =
    typeof IntersectionObserver === "undefined" ? true : initialElementVisible;
  let lastActive: boolean | undefined;

  const notify = () => {
    const active = documentVisible && elementVisible;
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
    observer?.disconnect();
  };
}

export function useRenderActivity(
  ref: RefObject<Element | null>,
  initialActive = true,
) {
  // Keep server and first client render aligned; the observer corrects this
  // immediately after mount.
  const [active, setActive] = useState(initialActive);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    return observeRenderActivity(element, setActive, initialActive);
  }, [initialActive, ref]);

  return active;
}
