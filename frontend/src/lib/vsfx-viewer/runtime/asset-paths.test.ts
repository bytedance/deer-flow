import { describe, expect, test } from "vitest";

import {
  VISUALIZE_JS_PUBLIC_URL,
  VISUALIZE_WASM_PUBLIC_URL,
  getVisualizeAssetPaths,
} from "@/lib/vsfx-viewer/runtime/asset-paths";

describe("Visualize public asset paths", () => {
  test("locks the vendored Visualize.js script URL", () => {
    expect(VISUALIZE_JS_PUBLIC_URL).toBe("/visualizejs/Visualize.js");
  });

  test("locks the vendored Visualize.js wasm URL", () => {
    expect(VISUALIZE_WASM_PUBLIC_URL).toBe("/visualizejs/Visualize.js.wasm");
  });

  test("returns both public URLs from the central shim", () => {
    expect(getVisualizeAssetPaths()).toEqual({
      scriptUrl: "/visualizejs/Visualize.js",
      wasmUrl: "/visualizejs/Visualize.js.wasm",
    });
  });
});
