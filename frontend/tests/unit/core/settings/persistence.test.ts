import { expect, test } from "@rstest/core";

import {
  diffPersistedUserSettings,
  parsePersistedUserSettings,
  parsePersistedUserSettingsPatch,
  toPersistedUserSettings,
} from "@/core/settings/persistence";

test("the server projection allowlists base settings and excludes thread/private state", () => {
  const projected = toPersistedUserSettings({
    notification: { enabled: true, permission: "granted" },
    tokenUsage: { headerTotal: false, inlineMode: "off" },
    context: {
      model_name: "model-a",
      mode: "pro",
      reasoning_effort: "high",
      thread_id: "private-thread",
      agent_name: "private-agent",
      token: "secret",
    },
  } as never);

  expect(projected).toEqual({
    notification: { enabled: true },
    tokenUsage: { headerTotal: false, inlineMode: "off" },
    context: {
      model_name: "model-a",
      mode: "pro",
      reasoning_effort: "high",
    },
  });
});

test("rejects malformed or oversized server/local settings", () => {
  expect(
    parsePersistedUserSettings({
      notification: { enabled: "yes" },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: {},
    }),
  ).toBeNull();

  expect(
    parsePersistedUserSettings({
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: { model_name: "x".repeat(257) },
    }),
  ).toBeNull();
});

test("rejects empty patches at the same boundary as the Gateway schema", () => {
  expect(parsePersistedUserSettingsPatch({})).toBeNull();
  expect(parsePersistedUserSettingsPatch({ context: {} })).toBeNull();
  expect(parsePersistedUserSettingsPatch({ tokenUsage: {} })).toBeNull();
});

test("snapshot diffs contain only changed leaves and encode removals as null", () => {
  expect(
    diffPersistedUserSettings(
      {
        notification: { enabled: true },
        tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
        context: { model_name: "old-model", mode: "thinking" },
      },
      {
        notification: { enabled: true },
        tokenUsage: { headerTotal: true, inlineMode: "off" },
        context: { mode: "thinking" },
      },
    ),
  ).toEqual({
    tokenUsage: { inlineMode: "off" },
    context: { model_name: null },
  });
});
