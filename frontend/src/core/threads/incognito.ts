/**
 * Incognito (temporary) chat helpers.
 *
 * The Gateway reports the live idle window in `/api/features`; the workspace
 * spells it in the largest unit that stays readable: minutes below an hour,
 * hours up to 72 hours, then whole days plus whole hours. A window that is not
 * an exact multiple of the unit shown is marked approximate instead of being
 * rounded in silence. Unit words live in the locale files, not here.
 */

export type IncognitoLifetimeUnit = "minutes" | "hours" | "days";

export interface IncognitoLifetimeParts {
  count: number;
  unit: IncognitoLifetimeUnit;
  /** Hours shown after a day count ("3 days 1 hour"); 0 when not needed. */
  remainderHours: number;
  /** The configured window is not exactly the duration shown. */
  approximate: boolean;
}

/** The locale functions needed to spell a lifetime. */
export interface IncognitoLifetimeText {
  durationMinutes: (count: number) => string;
  durationHours: (count: number) => string;
  durationDays: (count: number) => string;
  durationDaysHours: (days: number, hours: number) => string;
  approximately: (duration: string) => string;
}

const MINUTE_SECONDS = 60;
const HOUR_SECONDS = 60 * MINUTE_SECONDS;
const DAY_SECONDS = 24 * HOUR_SECONDS;
const MAX_HOUR_UNIT_VALUE = 72;

/**
 * Split a configured window into display units.
 *
 * Hours cover everything up to 72 hours, so 48 hours reads "48 hours" and 72
 * hours still does; only a longer window switches to days. The switch follows
 * the rounded value, so 72h40m reads as "about 3 days 1 hour" rather than
 * "73 hours".
 */
export function incognitoLifetimeParts(seconds: number): IncognitoLifetimeParts {
  const total = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;

  if (total < HOUR_SECONDS) {
    const minutes = Math.max(1, Math.round(total / MINUTE_SECONDS));
    if (minutes >= MINUTE_SECONDS) {
      // 59.5 minutes rounds up to a full hour.
      return {
        count: 1,
        unit: "hours",
        remainderHours: 0,
        approximate: true,
      };
    }
    return {
      count: minutes,
      unit: "minutes",
      remainderHours: 0,
      approximate: total % MINUTE_SECONDS !== 0,
    };
  }

  const hours = Math.round(total / HOUR_SECONDS);
  if (hours <= MAX_HOUR_UNIT_VALUE) {
    return {
      count: hours,
      unit: "hours",
      remainderHours: 0,
      approximate: total % HOUR_SECONDS !== 0,
    };
  }

  const days = Math.floor(hours / 24);
  const remainderHours = hours % 24;
  return {
    count: days,
    unit: "days",
    remainderHours,
    // Days alone are exact only for a whole-day window; "N days M hours" is
    // exact whenever the seconds land on a whole hour.
    approximate:
      remainderHours === 0
        ? total % DAY_SECONDS !== 0
        : total % HOUR_SECONDS !== 0,
  };
}

/** Spell a lifetime with the locale's unit words, marking inexact windows. */
export function incognitoLifetimeLabel(
  parts: IncognitoLifetimeParts,
  text: IncognitoLifetimeText,
): string {
  let duration: string;
  if (parts.unit === "minutes") {
    duration = text.durationMinutes(parts.count);
  } else if (parts.unit === "hours") {
    duration = text.durationHours(parts.count);
  } else if (parts.remainderHours > 0) {
    duration = text.durationDaysHours(parts.count, parts.remainderHours);
  } else {
    duration = text.durationDays(parts.count);
  }
  return parts.approximate ? text.approximately(duration) : duration;
}
