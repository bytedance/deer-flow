import { z } from "zod";

const gatewayConfigSchema = z.object({
  internalGatewayUrl: z.string().url(),
  trustedOrigins: z.array(z.string()).min(1),
});

export type GatewayConfig = z.infer<typeof gatewayConfigSchema>;

let _cached: GatewayConfig | null = null;

export function getGatewayConfig(): GatewayConfig {
  if (_cached) return _cached;

  const isDev = process.env.NODE_ENV === "development";

  const rawUrl = process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim();
  const internalGatewayUrl =
    rawUrl?.replace(/\/+$/, "") ??
    (isDev ? "http://localhost:8001" : undefined);

  const rawOrigins = process.env.DEER_FLOW_TRUSTED_ORIGINS?.trim();
  const trustedOrigins = rawOrigins
    ? rawOrigins
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    : isDev
      ? ["http://localhost:3000"]
      : undefined;

  _cached = gatewayConfigSchema.parse({ internalGatewayUrl, trustedOrigins });
  return _cached;
}
