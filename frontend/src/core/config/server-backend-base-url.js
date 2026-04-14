export function getServerBackendBaseURL() {
  const explicitBaseUrl = process.env.NEXT_PUBLIC_BACKEND_BASE_URL?.trim();
  if (explicitBaseUrl) {
    return explicitBaseUrl.replace(/\/+$/, "");
  }

  const internalGatewayBaseUrl =
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim();
  if (internalGatewayBaseUrl) {
    return internalGatewayBaseUrl.replace(/\/+$/, "");
  }

  return "http://127.0.0.1:8001";
}
