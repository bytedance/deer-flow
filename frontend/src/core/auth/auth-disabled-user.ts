import type { User } from "./types";

export const AUTH_DISABLED_USER: User = {
  id: "default",
  email: "default@test.local",
  system_role: "admin",
  needs_setup: false,
};

const PRODUCTION_ENV_VALUES = new Set(["prod", "production"]);

function isExplicitProductionEnvironment() {
  return ["DEER_FLOW_ENV", "ENVIRONMENT"].some((name) =>
    PRODUCTION_ENV_VALUES.has((process.env[name] ?? "").trim().toLowerCase()),
  );
}

export function isAuthDisabledMode() {
  return (
    process.env.DEER_FLOW_AUTH_DISABLED === "1" &&
    !isExplicitProductionEnvironment()
  );
}
