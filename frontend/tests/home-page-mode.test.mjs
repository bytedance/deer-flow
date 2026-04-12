import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/app/home-page-mode.js"),
).href;

const { shouldRedirectHomePageToWorkspace } = await import(helperPath);

void test("web builds keep the landing page at the home route", () => {
  assert.equal(
    shouldRedirectHomePageToWorkspace({ DEER_FLOW_DESKTOP_BUNDLE: undefined }),
    false,
  );
});

void test("desktop bundle redirects the home route to the workspace", () => {
  assert.equal(
    shouldRedirectHomePageToWorkspace({ DEER_FLOW_DESKTOP_BUNDLE: "1" }),
    true,
  );
});
