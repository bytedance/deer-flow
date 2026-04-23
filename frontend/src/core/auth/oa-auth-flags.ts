import { env } from "@/env";

function truthyFlag(v: string | undefined): boolean {
  if (!v) return false;
  const s = v.trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes";
}

export function isOaAuthEnabled(): boolean {
  return truthyFlag(env.NEXT_PUBLIC_OA_AUTH_ENABLED);
}
