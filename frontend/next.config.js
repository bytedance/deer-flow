/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

import nextra from "nextra";

const withNextra = nextra({});

/** @type {import("next").NextConfig} */
const config = {
  output:
    process.env.NEXT_CONFIG_BUILD_OUTPUT === "standalone"
      ? "standalone"
      : undefined,
  // Next.js enables gzip compression in production by default, which buffers
  // the entire response body before sending. That breaks SSE
  // (text/event-stream) — every event arrives at the client in one batch at
  // connection close. Disable it so the streaming route handler in
  // src/app/api/[...path]/route.ts can flush Server-Sent Events as they
  // arrive. Gateway-side responses are not large; if compression is needed
  // for static assets, put a reverse proxy (nginx/caddy) in front.
  compression: false,
  i18n: {
    locales: ["en", "zh"],
    defaultLocale: "en",
  },
  devIndicators: false,
  // API requests are proxied by the streaming route handler in
  // src/app/api/[...path]/route.ts. Next.js dev-server rewrites buffer the
  // full response body, which breaks SSE (text/event-stream) — events arrive
  // at the client in one batch instead of streaming. The route handler
  // forwards ReadableStreams so Server-Sent Events stay real-time.
  async rewrites() {
    return [];
  },
};

export default withNextra(config);
