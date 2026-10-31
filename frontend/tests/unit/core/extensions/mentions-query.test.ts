import { expect, it, rs } from "@rstest/core";

import { searchExtensionMentions } from "@/core/extensions/mentions";
import type { LoadedContribution } from "@/core/extensions/registry";

it("truncates provider queries without splitting surrogate pairs", async () => {
  const search = rs.fn(async () => []);
  const entry: LoadedContribution = {
    namespace: "team",
    module: "team",
    entry: null,
    title: "Team",
    description: "",
    settings: { enabled: true },
    extension: {
      apiVersion: 1,
      module: "team",
      mentionProviders: [{ id: "people", label: "People", search }],
    },
  };
  const query = `${"a".repeat(255)}😀tail`;

  await searchExtensionMentions([entry], query, {
    locale: "en-US",
    signal: new AbortController().signal,
  });

  expect(search).toHaveBeenCalledWith(
    `${"a".repeat(255)}😀`,
    expect.any(Object),
  );
});
