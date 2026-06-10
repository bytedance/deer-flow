import { z } from "zod";

import { resolveInternalGatewayUrl } from "../gateway-url.js";

const gatewayConfigSchema = z.object({
  internalGatewayUrl: z.string().url(),
  trustedOrigins: z.array(z.string()).min(1),
});

export type GatewayConfig = z.infer<typeof gatewayConfigSchema>;

let _cached: GatewayConfig | null = null;

export function getGatewayConfig(): GatewayConfig {
  if (_cached) return _cached;

  const internalGatewayUrl = resolveInternalGatewayUrl();

  const rawOrigins = process.env.DEER_FLOW_TRUSTED_ORIGINS?.trim();
  const trustedOrigins = rawOrigins
    ? rawOrigins
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    : ["http://localhost:3000"];

  _cached = gatewayConfigSchema.parse({ internalGatewayUrl, trustedOrigins });
  return _cached;
}
