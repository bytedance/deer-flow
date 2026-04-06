export type VisualizeAssetPaths = Readonly<{
  scriptUrl: string;
  wasmUrl: string;
}>;

export const VISUALIZE_JS_PUBLIC_URL = "/visualizejs/Visualize.js";

export const VISUALIZE_WASM_PUBLIC_URL = `${VISUALIZE_JS_PUBLIC_URL}.wasm`;

export function getVisualizeAssetPaths(): VisualizeAssetPaths {
  return {
    scriptUrl: VISUALIZE_JS_PUBLIC_URL,
    wasmUrl: VISUALIZE_WASM_PUBLIC_URL,
  };
}
