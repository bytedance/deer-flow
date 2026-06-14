import { describe, expect, test } from "vitest";

import {
  hasConfiguredEnvValue,
  resolveInternalGatewayUrl,
} from "@/core/gateway-url.js";

describe("gateway URL helpers", () => {
  test("normalizes configured gateway and fallback URLs", () => {
    expect(
      resolveInternalGatewayUrl(
        { DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: " http://gateway/base/// " },
        "http://fallback///",
      ),
    ).toBe("http://gateway/base");

    expect(resolveInternalGatewayUrl({}, "http://fallback///")).toBe(
      "http://fallback",
    );
  });

  test("treats empty and whitespace env values as unconfigured", () => {
    expect(hasConfiguredEnvValue(undefined)).toBe(false);
    expect(hasConfiguredEnvValue("")).toBe(false);
    expect(hasConfiguredEnvValue("  \t ")).toBe(false);
    expect(hasConfiguredEnvValue("http://gateway")).toBe(true);
  });
});
