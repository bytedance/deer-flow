/**
 * Run `构建` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

/** @类型 {import("下一个").NextConfig} */
const config = {
  devIndicators: false,
};

export default config;
