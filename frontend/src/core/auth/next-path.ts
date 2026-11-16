export const DEFAULT_AUTH_NEXT_PATH = "/workspace";

// The URL parser deletes tab, LF and CR before parsing, so `/\n//evil.example`
// passes the `//` check below and then navigates to `//evil.example`.
// Reject every C0 control and DEL rather than only the three it strips.
function hasControlCharacter(value: string): boolean {
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 0x20 || code === 0x7f) {
      return true;
    }
  }
  return false;
}

export function validateAuthNextPath(
  nextPath: string | null | undefined,
): string | null {
  if (!nextPath) {
    return null;
  }
  if (!nextPath.startsWith("/")) {
    return null;
  }
  if (nextPath.startsWith("//")) {
    return null;
  }
  if (nextPath.includes("\\") || nextPath.includes(":")) {
    return null;
  }
  if (hasControlCharacter(nextPath)) {
    return null;
  }
  return nextPath;
}

export function resolveAuthNextPath(
  nextPath: string | null | undefined,
  fallback = DEFAULT_AUTH_NEXT_PATH,
): string {
  return validateAuthNextPath(nextPath) ?? fallback;
}
