export const DEFAULT_AUTH_NEXT_PATH = "/workspace";

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
  return nextPath;
}

export function resolveAuthNextPath(
  nextPath: string | null | undefined,
  fallback = DEFAULT_AUTH_NEXT_PATH,
): string {
  return validateAuthNextPath(nextPath) ?? fallback;
}
