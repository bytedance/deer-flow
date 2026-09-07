/**
 * Module-level live count of active login-redirect deferrals.
 *
 * The count must be readable from *outside* React as well as inside: the
 * API fetcher's automatic 401 redirect is a hard ``window.location``
 * navigation that bypasses the router entirely, so it cannot consult
 * provider state through a closure — and a closure would be stale anyway
 * for a request that was already in flight when a deferral armed (the
 * exact window the imperative arm exists for). The provider owns the
 * React mirror of this value for rendering/effect purposes; this module
 * is the single source of truth for the *live* count.
 */

let loginRedirectDeferrals = 0;

/** Adjust the count by one arm/release pair and return the new value. */
export function adjustLoginRedirectDeferral(active: boolean): number {
  loginRedirectDeferrals = active
    ? loginRedirectDeferrals + 1
    : Math.max(0, loginRedirectDeferrals - 1);
  return loginRedirectDeferrals;
}

/** The live count — never a stale closure snapshot. */
export function isLoginRedirectDeferred(): boolean {
  return loginRedirectDeferrals > 0;
}
