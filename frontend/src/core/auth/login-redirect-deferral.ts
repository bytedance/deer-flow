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

/** Receiver for a login redirect the API fetcher suppressed. */
type DeferredUnauthorizedHandler = (target: string) => void;

let deferredUnauthorizedHandler: DeferredUnauthorizedHandler | null = null;

/**
 * Register the receiver for a login redirect the API fetcher suppressed
 * because a deferral held. The provider registers this so the suppressed
 * redirect is *handed over*, not dropped: it arms the held-redirect
 * machinery, which fires the target the moment the last deferral clears —
 * even when nothing else triggers a ``/me`` refresh afterwards. Without the
 * handover, every other consumer of ``UnauthorizedError`` (the model-load
 * banner withholds its warning, the models hook declines to retry) would
 * leave an unrelated expired-session 401 silent for the rest of the session.
 */
export function setDeferredUnauthorizedHandler(
  handler: DeferredUnauthorizedHandler | null,
): void {
  deferredUnauthorizedHandler = handler;
}

/** Emit a suppressed login-redirect target to the registered receiver. */
export function deferredUnauthorized(target: string): void {
  deferredUnauthorizedHandler?.(target);
}

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
