import { z } from "zod";

const gatewayConfigSchema = z.object({
  internalGatewayUrl: z.string().url(),
  trustedOrigins: z.array(z.string()).min(1),
});

export type GatewayConfig = z.infer<typeof gatewayConfigSchema>;

let _cached: GatewayConfig | null = null;

export function getGatewayConfig(): GatewayConfig {
  if (_cached) return _cached;

  const rawUrl = process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim();
  const internalGatewayUrl =
    rawUrl && rawUrl.length > 0
      ? rawUrl.replace(/\/+$/, "")
      : "http://127.0.0.1:8001";

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
