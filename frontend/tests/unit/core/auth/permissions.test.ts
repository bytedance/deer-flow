import { describe, expect, it } from "@rstest/core";

import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import { userSchema } from "@/core/auth/types";

describe("hasPermission", () => {
  it("grants a permission present in the resolved list", () => {
    expect(
      hasPermission(
        { permissions: ["threads:read", "threads:delete"] },
        PERMISSIONS.THREADS_DELETE,
      ),
    ).toBe(true);
  });

  it("denies a permission absent from the resolved list", () => {
    expect(
      hasPermission(
        { permissions: ["threads:read"] },
        PERMISSIONS.THREADS_DELETE,
      ),
    ).toBe(false);
  });

  it("treats an absent permissions field as permissive (pre-Phase-4 backend)", () => {
    // A mixed old-backend/new-frontend deploy must not hide actions the
    // caller can still perform — the Gateway route guards stay the
    // enforcement point, the UI field is advisory only.
    expect(hasPermission({}, PERMISSIONS.RUNS_CANCEL)).toBe(true);
  });

  it("treats a null permissions field as permissive", () => {
    // Credential-creation responses (register/initialize) serialize null;
    // they never advertise an empty grant set.
    expect(hasPermission({ permissions: null }, PERMISSIONS.RUNS_CANCEL)).toBe(
      true,
    );
  });

  it("treats a not-yet-loaded user as permissive", () => {
    expect(hasPermission(null, PERMISSIONS.THREADS_DELETE)).toBe(true);
    expect(hasPermission(undefined, PERMISSIONS.THREADS_DELETE)).toBe(true);
  });
});

describe("userSchema permissions field", () => {
  const baseUser = {
    id: "user-1",
    email: "user@example.test",
    system_role: "user" as const,
  };

  it("parses a /me payload that carries effective permissions", () => {
    const parsed = userSchema.parse({
      ...baseUser,
      permissions: ["threads:read", "runs:cancel"],
    });
    expect(parsed.permissions).toEqual(["threads:read", "runs:cancel"]);
  });

  it("parses a /me payload from a pre-Phase-4 backend (field absent)", () => {
    const parsed = userSchema.parse(baseUser);
    expect(parsed.permissions).toBeUndefined();
  });

  it("parses a credential-creation payload that carries null", () => {
    const parsed = userSchema.parse({ ...baseUser, permissions: null });
    expect(parsed.permissions).toBeNull();
  });
});
