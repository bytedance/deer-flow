/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

const allowedDevOrigins = [
  "localhost",
  "127.0.0.1",
  "::1",
  ...(process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean),
];

/** @type {import("next").NextConfig} */
const config = {
  allowedDevOrigins,
  devIndicators: false,
};

export default config;
