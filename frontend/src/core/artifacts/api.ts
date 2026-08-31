import { fetch } from "@/core/api/fetcher";

import { urlOfArtifact, urlOfArtifactArchive } from "./utils";

export interface ArtifactUpdateResponse {
  path: string;
  sha256: string;
  size: number;
}

export interface ArtifactArchiveDownload {
  blob: Blob;
  filename: string;
}

export const MAX_ARTIFACT_ARCHIVE_FILES = 50;

export class ArtifactRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ArtifactRequestError";
    this.status = status;
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  const data = (await response.json().catch(() => ({}))) as {
    detail?: string;
  };
  return data.detail ?? `HTTP ${response.status}: ${response.statusText}`;
}

export async function updateArtifactContent({
  threadId,
  filepath,
  content,
  expectedSha256,
}: {
  threadId: string;
  filepath: string;
  content: string;
  expectedSha256: string;
}): Promise<ArtifactUpdateResponse> {
  const response = await fetch(urlOfArtifact({ filepath, threadId }), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content,
      expected_sha256: expectedSha256,
    }),
  });
  if (!response.ok) {
    throw new ArtifactRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  return response.json() as Promise<ArtifactUpdateResponse>;
}

export async function downloadArtifactArchive({
  threadId,
  runId,
}: {
  threadId: string;
  runId: string;
}): Promise<ArtifactArchiveDownload> {
  const response = await fetch(urlOfArtifactArchive({ threadId, runId }), {
    method: "POST",
  });
  if (!response.ok) {
    throw new ArtifactRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1];
  return {
    blob: await response.blob(),
    filename: filename ?? `artifacts-${runId}.zip`,
  };
}
