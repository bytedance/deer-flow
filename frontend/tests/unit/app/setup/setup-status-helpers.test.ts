import { describe, expect, it } from "@rstest/core";

import { decideSetupModeFromSetupStatus } from "@/app/(auth)/setup/setup-status-helpers";

describe("decideSetupModeFromSetupStatus", () => {
  it("redirects to /login when the system is already set up", () => {
    expect(decideSetupModeFromSetupStatus(true, false)).toBe("redirect_login");
  });

  it("stays on init_admin when needs_setup is true", () => {
    expect(decideSetupModeFromSetupStatus(true, true)).toBe("init_admin");
  });

  it("fails safe to init_admin on a 429 rate-limited response", () => {
    // Regression for #2999: 429 used to be parsed as needs_setup=undefined
    // (falsy) and redirect the operator to /login, breaking first-boot.
    expect(decideSetupModeFromSetupStatus(false, undefined)).toBe("init_admin");
  });

  it("fails safe to init_admin on any other non-ok response", () => {
    expect(decideSetupModeFromSetupStatus(false, false)).toBe("init_admin");
    expect(decideSetupModeFromSetupStatus(false, true)).toBe("init_admin");
  });

  it("fails safe to init_admin when the body lacks needs_setup", () => {
    // 2xx with a malformed body — never silently send the operator to /login.
    expect(decideSetupModeFromSetupStatus(true, undefined)).toBe("init_admin");
  });
});
