import { expect } from "@rstest/core";

import { findRawIdentifiers } from "../../e2e/utils/raw-identifiers";

/**
 * DOM-test twin of `tests/e2e/utils/readable.ts`: assert that rendered text
 * shows no raw identifiers (IDs, UUIDs, ISO timestamps, cron strings,
 * enum/field names). Pass an element (its `textContent` is checked) or text.
 */
export function expectNoRawIdentifiers(target: Element | string): void {
  const text = typeof target === "string" ? target : (target.textContent ?? "");
  expect(findRawIdentifiers(text)).toEqual([]);
}
