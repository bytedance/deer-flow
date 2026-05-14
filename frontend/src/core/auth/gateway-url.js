export const DEFAULT_INTERNAL_GATEWAY_URL = "http://127.0.0.1:8001";

export function resolveInternalGatewayUrl(
  env = process.env,
  fallbackURL = DEFAULT_INTERNAL_GATEWAY_URL,
) {
  const configured = env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}
