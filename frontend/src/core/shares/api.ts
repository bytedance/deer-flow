import { z } from "zod";

import { fetch as authenticatedFetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export const shareLinkSchema = z.object({
  share_id: z.string(),
  checkpoint_id: z.string(),
  seq: z.number(),
  created_at: z.string(),
  expires_at: z.string(),
  revoked_at: z.string().nullable(),
});
export const sharedArtifactSchema = z.object({
  path: z.string(),
  mime_type: z.string(),
  sha256: z.string(),
  size: z.number(),
});
export const sharedConversationSchema = z.object({
  title: z.string(),
  checkpoint_id: z.string(),
  seq: z.number(),
  created_at: z.string(),
  expires_at: z.string(),
  messages: z.array(
    z.object({
      id: z.string(),
      type: z.enum(["human", "ai", "tool"]),
      content: z.string(),
      name: z.string().optional(),
    }),
  ),
  artifacts: z.array(sharedArtifactSchema),
});
export type ShareLink = z.infer<typeof shareLinkSchema>;
export type SharedArtifact = z.infer<typeof sharedArtifactSchema>;
export type SharedConversation = z.infer<typeof sharedConversationSchema>;

export class ShareError extends Error {
  constructor(readonly status: number) {
    super(`Share request failed (${status})`);
  }
}

async function checked(response: Response) {
  if (!response.ok) throw new ShareError(response.status);
  return response;
}

const sourceURL = (threadId: string) =>
  `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/shares`;
export const shareURL = (token: string) =>
  `${getBackendBaseURL()}/api/shares/${encodeURIComponent(token)}`;
export const shareArtifactURL = (token: string, path: string) =>
  `${shareURL(token)}/artifacts/${path.split("/").map(encodeURIComponent).join("/")}`;

export async function listShares(threadId: string, signal: AbortSignal) {
  return z.array(shareLinkSchema).parse(
    await (
      await checked(
        await authenticatedFetch(sourceURL(threadId), {
          signal,
          cache: "no-store",
        }),
      )
    ).json(),
  );
}

export async function createShare(
  threadId: string,
  expiresInSeconds: number,
  signal: AbortSignal,
) {
  const response = await checked(
    await authenticatedFetch(sourceURL(threadId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expires_in_seconds: expiresInSeconds }),
      signal,
    }),
  );
  return shareLinkSchema
    .extend({ token: z.string() })
    .parse(await response.json());
}

export async function revokeShare(
  threadId: string,
  shareId: string,
  signal: AbortSignal,
) {
  await checked(
    await authenticatedFetch(
      `${sourceURL(threadId)}/${encodeURIComponent(shareId)}`,
      { method: "DELETE", signal },
    ),
  );
}

export async function readShare(token: string, signal: AbortSignal) {
  const response = await checked(
    await globalThis.fetch(shareURL(token), {
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      signal,
    }),
  );
  return sharedConversationSchema.parse(await response.json());
}

export async function forkShare(
  token: string,
  requestId: string,
  signal: AbortSignal,
) {
  // Authenticate before a CSRF-protected POST, so anonymous visitors reach sign-in.
  await checked(
    await authenticatedFetch(`${getBackendBaseURL()}/api/v1/auth/me`, {
      cache: "no-store",
      signal,
    }),
  );
  const response = await checked(
    await authenticatedFetch(`${shareURL(token)}/fork`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId }),
      signal,
    }),
  );
  return z.object({ thread_id: z.string() }).parse(await response.json());
}
