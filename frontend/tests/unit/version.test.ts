import { afterEach, expect, test, rs } from "@rstest/core";

import pkg from "../../package.json";

const original = process.env.NEXT_PUBLIC_APP_VERSION;

afterEach(() => {
  rs.resetModules();
  if (original === undefined) {
    delete process.env.NEXT_PUBLIC_APP_VERSION;
  } else {
    process.env.NEXT_PUBLIC_APP_VERSION = original;
  }
});

test("APP_VERSION uses NEXT_PUBLIC_APP_VERSION when set (nightly build-arg)", async () => {
  process.env.NEXT_PUBLIC_APP_VERSION = "2.1.0-nightly.20260712-abc1234";
  const { APP_VERSION } = await import("@/version");
  expect(APP_VERSION).toBe("2.1.0-nightly.20260712-abc1234");
});

test("APP_VERSION falls back to package.json version when env is unset (local dev)", async () => {
  delete process.env.NEXT_PUBLIC_APP_VERSION;
  const { APP_VERSION } = await import("@/version");
  expect(APP_VERSION).toBe(pkg.version);
});

test("APP_VERSION treats an empty NEXT_PUBLIC_APP_VERSION as unset (release Docker build)", async () => {
  // The frontend Dockerfile sets ENV NEXT_PUBLIC_APP_VERSION="" when nightly CI
  // doesn't pass APP_VERSION; the empty string must fall through to the
  // package.json version just like an unset var.
  process.env.NEXT_PUBLIC_APP_VERSION = "";
  const { APP_VERSION } = await import("@/version");
  expect(APP_VERSION).toBe(pkg.version);
});
