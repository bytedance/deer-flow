/**
 * Wiki 更新状态可见 (2026-08-14): polling cadence + 更新中 derivation over
 * the entries payload's library-level generation flag. Mirrors
 * document-stats.test.ts — the wiring hook stays trivially thin.
 */
import { describe, expect, it } from "@rstest/core";

import { DOCUMENTS_POLL_INTERVAL_MS } from "@/core/knowledge/document-stats";
import type { WikiEntriesPage } from "@/core/knowledge/types";
import {
  isWikiUpdating,
  WIKI_ENTRIES_POLL_INTERVAL_MS,
  wikiEntriesRefetchInterval,
} from "@/core/knowledge/wiki-status";

const IDLE: WikiEntriesPage = { entries: [], generation: "idle", last_run: null };
const GENERATING: WikiEntriesPage = { entries: [], generation: "generating", last_run: null };

describe("wikiEntriesRefetchInterval", () => {
  it("never polls before the first payload lands or while idle", () => {
    expect(wikiEntriesRefetchInterval(undefined)).toBe(false);
    expect(wikiEntriesRefetchInterval(IDLE)).toBe(false);
  });

  it("polls at the shared 3s cadence while a generation run is in flight", () => {
    // Same source as the documents query — the two can never drift apart.
    expect(WIKI_ENTRIES_POLL_INTERVAL_MS).toBe(DOCUMENTS_POLL_INTERVAL_MS);
    expect(WIKI_ENTRIES_POLL_INTERVAL_MS).toBe(3000);
    expect(wikiEntriesRefetchInterval(GENERATING)).toBe(WIKI_ENTRIES_POLL_INTERVAL_MS);
  });
});

describe("isWikiUpdating", () => {
  it("is true while the trigger mutation is pending, even before the first poll", () => {
    expect(isWikiUpdating(undefined, true)).toBe(true);
    expect(isWikiUpdating(IDLE, true)).toBe(true);
  });

  it("follows the server flag once the mutation settles", () => {
    expect(isWikiUpdating(GENERATING, false)).toBe(true);
    expect(isWikiUpdating(IDLE, false)).toBe(false);
    expect(isWikiUpdating(undefined, false)).toBe(false);
  });
});
