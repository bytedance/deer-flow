import { v3 as uuidv3 } from "uuid";

/**
 * RFC 4122 UUID v3 (MD5) over ``namespace + normalized email`` — deterministic and unique per email.
 * Namespace is DeerFlow–specific so ids do not collide with other v3 uses.
 */
const OA_DEV_USER_NAMESPACE = "6deefc02-0a00-4000-8000-000000000001";

export function devUserIdFromEmail(email: string): string {
  const normalized = email.trim().toLowerCase();
  return uuidv3(normalized, OA_DEV_USER_NAMESPACE);
}
