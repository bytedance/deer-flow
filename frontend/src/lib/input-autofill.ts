/**
 * Autofill defenses for inputs that are NOT credentials for this origin.
 *
 * Chromium's password manager pairs a `type="password"` input with the nearest
 * preceding text input and fills both from the saved login for the site — which is
 * how the account email and password ended up in the model dialogs' endpoint and
 * API-key fields (2026-09-10 report). These attribute sets stop that without
 * disabling autofill for genuine login forms. `autoComplete="new-password"` is the
 * documented signal that suppresses saved-credential suggestions on a password
 * field; the `data-*` attributes cover 1Password / LastPass / Bitwarden / Dashlane.
 *
 * Mirrors the recipe already used by the channel runtime-config dialog's secret
 * fields. It keeps `type="password"` (which masks in every browser) instead of that
 * dialog's `-webkit-text-security` variant, which Firefox ignores.
 */
export const AUTOFILL_OFF_INPUT_PROPS = {
  autoComplete: "off",
  autoCorrect: "off",
  autoCapitalize: "none",
  spellCheck: false,
  "data-1p-ignore": "true",
  "data-bwignore": "true",
  "data-lpignore": "true",
  "data-form-type": "other",
} as const;

/** Adds the saved-credential suppression a password-type input needs. */
export const SECRET_INPUT_AUTOFILL_PROPS = {
  ...AUTOFILL_OFF_INPUT_PROPS,
  autoComplete: "new-password",
} as const;
