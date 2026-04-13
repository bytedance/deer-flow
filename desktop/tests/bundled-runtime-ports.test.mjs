import assert from "node:assert/strict";
import test from "node:test";

const { getBundledRuntimePorts, getBundledRuntimeEnv } = await import(
  "../dist/main/runtime-ports.js"
);

void test("bundled desktop runtime uses gateway port 8002 to avoid local source conflicts", () => {
  assert.deepEqual(getBundledRuntimePorts(), {
    gatewayPort: 8002,
    frontendPort: 3000,
  });
});

void test("bundled desktop frontend env points gateway and langgraph URLs at port 8002", () => {
  const env = getBundledRuntimeEnv();

  assert.equal(env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL, "http://127.0.0.1:8002");
  assert.equal(env.DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL, "http://127.0.0.1:8002/api");
});
