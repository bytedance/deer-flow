/**
 * Decision helper for the /setup page's setup-status probe.
 *
 * Extracted to a pure module so the fail-safe behaviour can be unit-tested
 * without rendering the page. See #2999: a rate-limited (429) or otherwise
 * non-ok response used to be parsed as ``{ needs_setup: undefined }``, which
 * is falsy and therefore sent the operator to /login instead of the
 * init-admin form — breaking first-boot setup until the rate-limit window
 * expired.
 */

export type SetupStatusDecision = "init_admin" | "redirect_login";

/**
 * Map a setup-status probe outcome to the page-level action.
 *
 * Fail-safe to ``init_admin`` whenever the response is non-ok or the body
 * does not explicitly say setup is done. Showing the init-admin form
 * unnecessarily is one extra page load; redirecting the operator away from
 * first-boot setup silently breaks admin creation.
 */
export function decideSetupModeFromSetupStatus(
  ok: boolean,
  needsSetup: boolean | undefined,
): SetupStatusDecision {
  if (ok && needsSetup === false) {
    return "redirect_login";
  }
  return "init_admin";
}
