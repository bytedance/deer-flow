import { expect, type Locator } from "@playwright/test";

import { findRawIdentifiers } from "./raw-identifiers";

/**
 * Assert that a default view shows no raw identifiers (IDs, UUIDs, ISO
 * timestamps, cron strings, enum/field names). IDs belong behind "Copy task
 * ID" and in `data-*` attributes; raw error text behind "Details".
 */
export async function expectNoRawIdentifiers(locator: Locator): Promise<void> {
  const text = await locator.innerText();
  expect(
    findRawIdentifiers(text),
    `raw identifiers in the visible text:\n${text}`,
  ).toEqual([]);
}
