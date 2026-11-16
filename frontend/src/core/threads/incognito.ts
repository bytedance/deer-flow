/**
 * Incognito (temporary) chat helpers.
 *
 * The Gateway reports the live idle window in `/api/features`; the workspace
 * renders it as the largest whole unit so a 24-hour default reads "1 day".
 * Unit words live in the locale files, not here.
 */

export type IncognitoLifetimeUnit = "minutes" | "hours" | "days";

export interface IncognitoLifetimeParts {
  count: number;
  unit: IncognitoLifetimeUnit;
}

const MINUTE_SECONDS = 60;
const HOUR_SECONDS = 60 * MINUTE_SECONDS;
const DAY_SECONDS = 24 * HOUR_SECONDS;

/** Round a positive duration to the largest whole minute, hour or day. */
export function incognitoLifetimeParts(
  seconds: number,
): IncognitoLifetimeParts {
  if (seconds >= DAY_SECONDS) {
    return {
      count: Math.max(1, Math.round(seconds / DAY_SECONDS)),
      unit: "days",
    };
  }
  if (seconds >= HOUR_SECONDS) {
    return {
      count: Math.max(1, Math.round(seconds / HOUR_SECONDS)),
      unit: "hours",
    };
  }
  return {
    count: Math.max(1, Math.round(seconds / MINUTE_SECONDS)),
    unit: "minutes",
  };
}
