/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

/** @type {import("next").NextConfig} */
const config = {
  devIndicators: false,
  // Suppress hydration warnings from Radix UI and other libraries
  // that generate random IDs on server and client
  onRecoverableError: (error, { componentStack }) => {
    // Ignore hydration-related recoverable errors
    if (error.message.includes('Hydration failed') || 
        error.message.includes('htmlAttribute') ||
        error.message.includes('suppressHydrationWarning')) {
      return;
    }
    console.error(error);
  },
};

export default config;
