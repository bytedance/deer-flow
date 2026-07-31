export type RenderActivityListener = (active: boolean) => void;

/**
 * Reports whether an element is both on screen and in a visible document.
 * Consumers can use this to suspend expensive animation loops without
 * unmounting and rebuilding their rendering state.
 */
export function observeRenderActivity(
  element: Element,
  listener: RenderActivityListener,
) {
  let documentVisible = !document.hidden;
  let elementVisible = true;
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
