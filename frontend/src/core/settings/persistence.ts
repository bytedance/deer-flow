import { z } from "zod";

import type { LocalSettings } from "./local";

const modelNameSchema = z.string().trim().min(1).max(256);
const modeSchema = z.enum(["flash", "thinking", "pro", "ultra"]);
const reasoningEffortSchema = z.enum(["minimal", "low", "medium", "high"]);
const inlineModeSchema = z.enum(["off", "per_turn", "step_debug"]);

export const persistedUserSettingsSchema = z
  .object({
    notification: z.object({ enabled: z.boolean() }).strict(),
    tokenUsage: z
      .object({
        headerTotal: z.boolean(),
        inlineMode: inlineModeSchema,
      })
      .strict(),
    context: z
      .object({
        model_name: modelNameSchema.optional(),
        mode: modeSchema.optional(),
        reasoning_effort: reasoningEffortSchema.optional(),
      })
      .strict(),
  })
  .strict();

const contextPatchSchema = z
  .object({
    model_name: modelNameSchema.nullable().optional(),
    mode: modeSchema.nullable().optional(),
    reasoning_effort: reasoningEffortSchema.nullable().optional(),
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0);

const tokenUsagePatchSchema = z
  .object({
    headerTotal: z.boolean().optional(),
    inlineMode: inlineModeSchema.optional(),
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0);

export const persistedUserSettingsPatchSchema = z
  .object({
    notification: z.object({ enabled: z.boolean() }).strict().optional(),
    tokenUsage: tokenUsagePatchSchema.optional(),
    context: contextPatchSchema.optional(),
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0);

export type PersistedUserSettings = z.infer<typeof persistedUserSettingsSchema>;
export type PersistedUserSettingsPatch = z.infer<
  typeof persistedUserSettingsPatchSchema
>;

const DEFAULT_PERSISTED_USER_SETTINGS: PersistedUserSettings = {
  notification: { enabled: true },
  tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
  context: {},
};

export function parsePersistedUserSettings(
  value: unknown,
): PersistedUserSettings | null {
  const parsed = persistedUserSettingsSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

export function parsePersistedUserSettingsPatch(
  value: unknown,
): PersistedUserSettingsPatch | null {
  const parsed = persistedUserSettingsPatchSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

/**
 * Project browser state onto the server's deliberately small allowlist.
 *
 * Thread ids/overrides, agent/workspace metadata, browser Notification
 * permission, and any accidental token-like fields are impossible to include
 * because this function constructs every accepted property explicitly.
 */
export function toPersistedUserSettings(
  settings: LocalSettings,
): PersistedUserSettings {
  const candidate = {
    notification: { enabled: settings.notification.enabled },
    tokenUsage: {
      headerTotal: settings.tokenUsage.headerTotal,
      inlineMode: settings.tokenUsage.inlineMode,
    },
    context: {
      ...(settings.context.model_name === undefined
        ? {}
        : { model_name: settings.context.model_name }),
      ...(settings.context.mode === undefined
        ? {}
        : { mode: settings.context.mode }),
      ...(settings.context.reasoning_effort === undefined
        ? {}
        : { reasoning_effort: settings.context.reasoning_effort }),
    },
  };
  return (
    parsePersistedUserSettings(candidate) ??
    structuredClone(DEFAULT_PERSISTED_USER_SETTINGS)
  );
}

export function toFullUserSettingsPatch(
  settings: PersistedUserSettings,
): PersistedUserSettingsPatch {
  return {
    notification: { ...settings.notification },
    tokenUsage: { ...settings.tokenUsage },
    context: {
      model_name: settings.context.model_name ?? null,
      mode: settings.context.mode ?? null,
      reasoning_effort: settings.context.reasoning_effort ?? null,
    },
  };
}

export function applyPersistedUserSettingsPatch(
  settings: PersistedUserSettings,
  patch: PersistedUserSettingsPatch,
): PersistedUserSettings {
  const context = { ...settings.context };
  const modelName = patch.context?.model_name;
  if (modelName === null) delete context.model_name;
  else if (modelName !== undefined) context.model_name = modelName;
  const mode = patch.context?.mode;
  if (mode === null) delete context.mode;
  else if (mode !== undefined) context.mode = mode;
  const reasoningEffort = patch.context?.reasoning_effort;
  if (reasoningEffort === null) delete context.reasoning_effort;
  else if (reasoningEffort !== undefined)
    context.reasoning_effort = reasoningEffort;
  return persistedUserSettingsSchema.parse({
    notification: {
      ...settings.notification,
      ...patch.notification,
    },
    tokenUsage: {
      ...settings.tokenUsage,
      ...patch.tokenUsage,
    },
    context,
  });
}

export function mergePersistedUserSettingsPatches(
  first: PersistedUserSettingsPatch | null,
  second: PersistedUserSettingsPatch,
): PersistedUserSettingsPatch {
  return persistedUserSettingsPatchSchema.parse({
    ...(first ?? {}),
    ...second,
    ...((first?.notification ?? second.notification) && {
      notification: {
        ...first?.notification,
        ...second.notification,
      },
    }),
    ...((first?.tokenUsage ?? second.tokenUsage) && {
      tokenUsage: {
        ...first?.tokenUsage,
        ...second.tokenUsage,
      },
    }),
    ...((first?.context ?? second.context) && {
      context: {
        ...first?.context,
        ...second.context,
      },
    }),
  });
}

export function fromPersistedUserSettings(
  settings: PersistedUserSettings,
): LocalSettings {
  return {
    notification: { ...settings.notification },
    tokenUsage: { ...settings.tokenUsage },
    context: { ...settings.context, mode: settings.context.mode },
  };
}
