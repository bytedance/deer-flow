import { describe, expect, it, rs } from "@rstest/core";

import {
  extensionMentionMetadata,
  referenceToken,
} from "@/components/workspace/mentions/inline-references";
import {
  extensionMentionId,
  parseExtensionMention,
  searchExtensionMentions,
} from "@/core/extensions/mentions";
import type { LoadedContribution } from "@/core/extensions/registry";

const entry = (
  namespace: string,
  search: (...args: never[]) => unknown,
): LoadedContribution => ({
  namespace,
  module: namespace,
  entry: null,
  title: namespace,
  description: "",
  settings: { enabled: true },
  extension: {
    apiVersion: 1,
    module: namespace,
    mentionProviders: [
      { id: "people", label: "People", search: search as never },
    ],
  },
});
describe("extension mentions", () => {
  it("keeps identities distinct and round trips Unicode and punctuation", () => {
    const reference = {
      namespace: "community.team",
      provider: "people",
      id: "陈 ()/1",
      label: "陈",
    };
    expect(
      parseExtensionMention(extensionMentionId(reference), reference.label),
    ).toEqual(reference);
    expect(parseExtensionMention('["team","people",{}]', "Bad")).toBeNull();
  });
  it("isolates rejected providers and rejects invalid or duplicate candidates", async () => {
    const result = await searchExtensionMentions(
      [
        entry("broken", async () => {
          throw Error("offline");
        }),
        entry("team", async () => [
          { id: "a", label: "Alice" },
          { id: "a", label: "Duplicate" },
          { id: {}, label: "Invalid" },
        ]),
        {
          ...entry("disabled", async () => [{ id: "b", label: "Bob" }]),
          settings: { enabled: false },
        },
      ],
      "ali",
      {
        locale: "en-US",
        threadId: "thread",
        signal: new AbortController().signal,
      },
    );
    expect(result.items).toEqual([
      {
        namespace: "team",
        provider: "people",
        id: "a",
        label: "Alice",
        description: "People",
      },
    ]);
    expect(result.failed).toBe(true);
  });
  it("settles even if a provider ignores cancellation", async () => {
    const abort = new AbortController();
    const pending = searchExtensionMentions(
      [entry("team", () => new Promise(() => undefined))],
      "",
      { locale: "en-US", signal: abort.signal },
    );
    abort.abort();
    await expect(pending).rejects.toThrow();
  });
});

it("deduplicates selected tokens and drops removed or malformed metadata", () => {
  const reference = {
    namespace: "community.team",
    provider: "people",
    id: "陈/1",
    label: "陈",
  };
  const token = referenceToken(
    "extension",
    extensionMentionId(reference),
    reference.label,
  );
  expect(extensionMentionMetadata(`${token} ${token}`)).toEqual({
    extension_mentions: [reference],
  });
  expect(extensionMentionMetadata("@陈")).toEqual({});
  expect(
    extensionMentionMetadata(referenceToken("extension", "not-json", "Bad")),
  ).toEqual({});
});

it("times out an unresponsive provider without losing healthy candidates", async () => {
  rs.useFakeTimers();
  try {
    const pending = searchExtensionMentions(
      [
        entry("slow", () => new Promise(() => undefined)),
        entry("fast", async () => [{ id: "one", label: "Ready" }]),
      ],
      "",
      { locale: "en-US", signal: new AbortController().signal },
    );
    await rs.advanceTimersByTimeAsync(3000);
    const result = await pending;
    expect(result.items.map((item) => item.id)).toEqual(["one"]);
    expect(result.failed).toBe(true);
  } finally {
    rs.useRealTimers();
  }
});
