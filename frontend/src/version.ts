/**
 * App version shown in the UI (About page, etc.). Prefers the build-time
 * NEXT_PUBLIC_APP_VERSION, which nightly CI sets to
 * `<base>-nightly.<YYYYMMDD>-<short_sha>` (matching the Helm chart's nightly
 * scheme). Falls back to package.json's version for local dev and tag-driven
 * release builds, where package.json is verified to match the git tag
 * (see scripts/verify_versions.sh + .github/workflows/verify-versions.yml).
 */
import pkg from "../package.json";

// `||` (not `??`) is intentional: the frontend Dockerfile sets
// NEXT_PUBLIC_APP_VERSION="" for release/local builds, and that empty string
// must fall through to pkg.version just like an unset var. `??` would keep "".
// eslint-disable-next-line @typescript-eslint/prefer-nullish-coalescing
export const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || pkg.version;
