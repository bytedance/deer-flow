import { z } from "zod";

export interface WorkspaceCapability {
  readonly enabled: boolean;
  readonly available: boolean;
}
const responseSchema = z.object({
  workspaces: z
    .object({ enabled: z.boolean(), available: z.boolean() })
    .optional(),
});

/** Absence is legacy; malformed or contradictory metadata is never legacy. */
export function parseWorkspaceCapability(value: unknown): WorkspaceCapability {
  const parsed = responseSchema.safeParse(value);
  if (!parsed.success)
    throw new Error("Workspace capability could not be confirmed");
  const capability = parsed.data.workspaces ?? {
    enabled: false,
    available: false,
  };
  if (capability.available && !capability.enabled)
    throw new Error("Inconsistent workspace capability");
  return Object.freeze(capability);
}
