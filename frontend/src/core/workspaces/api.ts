import { z } from "zod";

import { parseGatewayApiError } from "@/core/api/errors";
import { getBackendBaseURL } from "@/core/config";

const uuid = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
const version = z.number().int().min(1).max(Number.MAX_SAFE_INTEGER);
const workspaceRow = z.object({
  id: uuid,
  name: z
    .string()
    .min(1)
    .refine((name) => Array.from(name).length <= 128),
  kind: z.enum(["personal", "team"]),
  status: z.literal("active"),
  personal_user_id: z.string().nullable(),
  role: z.enum(["owner", "admin", "member"]),
  membership_version: version,
  policy_version: version,
});
const contextRow = z.object({
  workspace_id: uuid,
  actor_user_id: z
    .string()
    .min(1)
    .max(64)
    .refine(
      (actor) =>
        actor.trim() === actor &&
        Array.from(actor).every(
          (character) =>
            character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127,
        ),
    ),
  membership_version: version,
  policy_version: version,
});

export interface Workspace {
  readonly id: string;
  readonly name: string;
  readonly kind: "personal" | "team";
  readonly role: "owner" | "admin" | "member";
  readonly membershipVersion: number;
  readonly policyVersion: number;
}

/** Server metadata projection; not a browser-issued authorization grant. */
export interface WorkspaceContextProjection {
  readonly workspaceId: string;
  readonly actorUserId: string;
  readonly membershipVersion: number;
  readonly policyVersion: number;
}

export class WorkspaceResponseError extends Error {
  constructor() {
    super("Workspace metadata could not be confirmed");
    this.name = "WorkspaceResponseError";
  }
}

export async function readWorkspaceSelection(
  actorUserId: string,
  selector: string | undefined,
  signal: AbortSignal,
) {
  const origin =
    typeof window === "undefined"
      ? "http://localhost:2026"
      : window.location.origin;
  const root = new URL(`${getBackendBaseURL()}/api/workspaces`, origin);
  if (root.username || root.password) throw new WorkspaceResponseError();
  // These are fixed read-only control-plane endpoints, before a content scope
  // exists. Use the native session cookie; never manufacture an actor header.
  // Unlike the general fetcher, old metadata cannot trigger a login redirect.
  const read = async (suffix: string, selected?: string): Promise<unknown> => {
    signal.throwIfAborted();
    const headers = new Headers();
    if (selected) headers.set("X-Deerflow-Workspace", selected);
    const response = await globalThis.fetch(`${root.toString()}${suffix}`, {
      method: "GET",
      headers,
      credentials: "include",
      redirect: "error",
      cache: "no-store",
      signal,
    });
    signal.throwIfAborted();
    let body: unknown;
    try {
      body = await response.json();
    } catch (error) {
      signal.throwIfAborted();
      if (response.ok) throw error;
      body = {};
    }
    signal.throwIfAborted();
    if (!response.ok)
      throw parseGatewayApiError(
        body,
        response.status,
        "Workspace metadata unavailable",
      );
    return body;
  };

  const parsed = z.array(workspaceRow).safeParse(await read(""));
  if (!parsed.success) throw new WorkspaceResponseError();
  const rows = parsed.data;
  const personal = rows.filter((row) => row.kind === "personal");
  if (
    new Set(rows.map((row) => row.id)).size !== rows.length ||
    personal.length !== 1 ||
    personal[0]?.personal_user_id !== actorUserId ||
    personal[0]?.role !== "owner" ||
    rows.some((row) => row.kind === "team" && row.personal_user_id !== null)
  )
    throw new WorkspaceResponseError();
  const selected =
    selector === undefined
      ? personal[0]
      : rows.find((row) => row.id === selector);
  if (!selected) throw new WorkspaceResponseError();
  const confirmed = contextRow.safeParse(await read("/current", selected.id));
  if (
    !confirmed.success ||
    confirmed.data.actor_user_id !== actorUserId ||
    confirmed.data.workspace_id !== selected.id ||
    confirmed.data.membership_version !== selected.membership_version ||
    confirmed.data.policy_version !== selected.policy_version
  )
    throw new WorkspaceResponseError();
  signal.throwIfAborted();
  const workspaces: readonly Workspace[] = Object.freeze(
    rows.map((row) =>
      Object.freeze({
        id: row.id,
        name: row.name,
        kind: row.kind,
        role: row.role,
        membershipVersion: row.membership_version,
        policyVersion: row.policy_version,
      }),
    ),
  );
  const context: WorkspaceContextProjection = Object.freeze({
    workspaceId: confirmed.data.workspace_id,
    actorUserId: confirmed.data.actor_user_id,
    membershipVersion: confirmed.data.membership_version,
    policyVersion: confirmed.data.policy_version,
  });
  // Do not expose names or roles from a newly fetched list before confirming
  // that the server still sees this actor, selector and version pair.
  return Object.freeze({ workspaces, context });
}
