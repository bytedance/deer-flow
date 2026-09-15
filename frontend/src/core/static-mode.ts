import { env } from "@/env";

export function isStaticWebsiteOnly() {
  return env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
}
