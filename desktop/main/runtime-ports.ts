export function getBundledRuntimePorts() {
  return {
    gatewayPort: 8002,
    frontendPort: 3000,
  };
}

export function getBundledFrontendURL() {
  return `http://127.0.0.1:${getBundledRuntimePorts().frontendPort}`;
}

export function getBundledRuntimeEnv() {
  const { gatewayPort, frontendPort } = getBundledRuntimePorts();

  return {
    ELECTRON_RUN_AS_NODE: "1",
    HOSTNAME: "127.0.0.1",
    PORT: String(frontendPort),
    NODE_ENV: "production",
    BETTER_AUTH_SECRET: "deerflow-desktop-bundled-secret",
    BETTER_AUTH_BASE_URL: getBundledFrontendURL(),
    DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: `http://127.0.0.1:${gatewayPort}`,
    DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL: `http://127.0.0.1:${gatewayPort}/api`,
  };
}
