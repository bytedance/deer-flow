import * as React from "react";

/* Breakpoint boundaries for responsive hooks.
 *
 * - PHONE: anything below the Tailwind ``sm`` breakpoint. Covers iPhone 14
 *   (390), 14 Pro (393), 14 Plus (428) and 14 Pro Max (430) in portrait.
 * - NARROW: anything below the Tailwind ``lg`` breakpoint (1024). Covers
 *   all phones plus tablets in portrait, including Galaxy Tab S9 (800),
 *   S9+ (~876) and S9 Ultra (~924). Below this width the UI switches to
 *   drawer-based navigation and single-column layouts; above, it uses
 *   the persistent sidebar + side-by-side artifact panel.
 */
const PHONE_MAX = 640;
const NARROW_MAX = 1024;

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = React.useState<boolean | undefined>(undefined);
  React.useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return !!matches;
}

/** True on phone-sized viewports (< 640 px). */
export function useIsPhone(): boolean {
  return useMediaQuery(`(max-width: ${PHONE_MAX - 1}px)`);
}

/** True on tablet-portrait and below (< 1024 px) — the single-column mode. */
export function useIsNarrow(): boolean {
  return useMediaQuery(`(max-width: ${NARROW_MAX - 1}px)`);
}

/** True specifically on tablet-portrait range (640 – 1023 px). */
export function useIsTablet(): boolean {
  return useMediaQuery(
    `(min-width: ${PHONE_MAX}px) and (max-width: ${NARROW_MAX - 1}px)`,
  );
}

/** Backwards-compatible alias. "Mobile" here covers phone + tablet portrait —
 *  i.e. every viewport where the persistent desktop sidebar does not fit
 *  alongside a usable chat column. Consumers relying on the old 768 px
 *  threshold are now aligned with the single-column-layout threshold at
 *  1024 px, which matches the post-Galaxy-Tab-S9-integration design. */
export function useIsMobile(): boolean {
  return useIsNarrow();
}
