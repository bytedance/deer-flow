import { resolve } from "path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  test: {
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    // Node by default. DOM-dependent suites opt in per-file with a
    // `// @vitest-environment jsdom` docblock (see tasks/context.test.tsx).
    // A global jsdom env breaks node-only tests that resolve fixtures via
    // `import.meta.url` — jsdom's module URL is not a `file:` URL, e.g.
    // tasks/subtask-result.test.ts reading the cross-language contract.
    environment: "node",
    globals: true,
  },
});
