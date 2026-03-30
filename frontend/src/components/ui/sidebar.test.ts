import assert from "node:assert/strict";
import test from "node:test";

const { shouldRenderMobileSidebarSheet } = await import(
  new URL("./sidebar-render-mode.ts", import.meta.url).href
);

void test("uses sheet for mobile offcanvas sidebars", () => {
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: true,
      collapsible: "offcanvas",
      state: "collapsed",
    }),
    true,
  );
});

void test("keeps collapsed icon-collapsible sidebars visible on mobile", () => {
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: true,
      collapsible: "icon",
      state: "collapsed",
    }),
    false,
  );
});

void test("still uses sheet for expanded icon-collapsible sidebars on mobile", () => {
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: true,
      collapsible: "icon",
      state: "expanded",
    }),
    true,
  );
});

void test("does not use sheet on desktop", () => {
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: false,
      collapsible: "offcanvas",
      state: "collapsed",
    }),
    false,
  );
});

void test("mobile with none collapsible uses sheet (collapsed)", () => {
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: true,
      collapsible: "none",
      state: "collapsed",
    }),
    true,
  );
});

void test("mobile with none collapsible uses sheet (expanded)", () => {
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: true,
      collapsible: "none",
      state: "expanded",
    }),
    true,
  );
});

void test("desktop with icon collapsible never uses sheet", () => {
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: false,
      collapsible: "icon",
      state: "collapsed",
    }),
    false,
  );
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: false,
      collapsible: "icon",
      state: "expanded",
    }),
    false,
  );
});

void test("mobile offcanvas expanded uses sheet", () => {
  assert.equal(
    shouldRenderMobileSidebarSheet({
      isMobile: true,
      collapsible: "offcanvas",
      state: "expanded",
    }),
    true,
  );
});
