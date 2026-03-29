import assert from "node:assert/strict";
import test from "node:test";

const { getPreflightOutcome } = await import(new URL("./preflight.js", import.meta.url).href);

void test("redirects to the localhost new-chat URL when the models check succeeds", () => {
  assert.deepEqual(getPreflightOutcome({ ok: true }), {
    shouldRedirect: true,
    redirectUrl: "http://localhost:2026/workspace/chats/new",
  });
});

void test("stays on the fallback page when the models check fails", () => {
  assert.deepEqual(getPreflightOutcome({ ok: false }), {
    shouldRedirect: false,
    redirectUrl: null,
  });
});

void test("stays on the fallback page when the request errors", () => {
  assert.deepEqual(getPreflightOutcome({ ok: false, error: new Error("offline") }), {
    shouldRedirect: false,
    redirectUrl: null,
  });
});
