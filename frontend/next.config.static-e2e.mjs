// E2E-only Next.js config for the "static-website" Playwright project.
//
// The marketing landing page (frontend/src/app/page.tsx) is only rendered when
// NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true. The main e2e webServer runs a full
// deployment where `/` now redirects into the app (#3909), so the landing page
// can't be exercised there. This config lets a second webServer build/serve the
// static marketing site on a separate port and a separate distDir (`.next-static`)
// so it never clobbers the main `.next` output.
import base from "./next.config.js";

/** @type {import("next").NextConfig} */
const config = {
  ...base,
  distDir: ".next-static",
};

export default config;
