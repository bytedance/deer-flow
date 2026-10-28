/**
 * Permissive email syntax check used by the auth password forms.
 * Surrounding whitespace is accepted; callers must submit the trimmed address.
 *
 * The backend identity schema deliberately accepts addresses that stricter
 * validators reject — see `emailSchema` in `@/core/auth/types`, which is a
 * bare `z.string().min(1)` because API-created accounts, administrators and
 * OIDC identities may carry addresses such as a non-ASCII local part.
 *
 * The browser's `type="email"` constraint validation, however, rejects any
 * non-ASCII local part before the form's submit handler ever runs, so an
 * account like `用户@example.com` could never sign in through the password
 * form even though the auth API happily issues a session for it (#7488).
 *
 * The auth forms therefore disable native constraint validation (`noValidate`)
 * and apply this check in JS instead. It must stay strictly weaker than what
 * the backend accepts: exactly one "@", a non-empty local part and domain,
 * and no whitespace. Anything beyond that is left to the backend, which is
 * the authority on which addresses can hold an account.
 */
export function isValidEmail(value: string): boolean {
  const address = value.trim();
  const at = address.indexOf("@");
  if (at <= 0 || at !== address.lastIndexOf("@")) {
    return false;
  }
  const domain = address.slice(at + 1);
  if (!domain) {
    return false;
  }
  return !/\s/.test(address);
}
