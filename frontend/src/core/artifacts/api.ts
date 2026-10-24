import { requestArtifact, type ArtifactRequestOptions } from "./request";
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

export interface ArtifactArchiveManifest {
  fileCount: number;
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

export async function updateArtifactContent(
  {
    threadId,
    filepath,
    content,
    expectedSha256,
  }: {
    threadId: string;
    filepath: string;
    content: string;
    expectedSha256: string;
  },
  options?: ArtifactRequestOptions,
): Promise<ArtifactUpdateResponse> {
  return requestArtifact(
    urlOfArtifact({ filepath, threadId }),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content,
        expected_sha256: expectedSha256,
      }),
    },
    async (response) => {
      if (!response.ok) {
        throw new ArtifactRequestError(
          response.status,
          await readErrorDetail(response),
        );
      }
      return response.json() as Promise<ArtifactUpdateResponse>;
    },
    options,
  );
}

export async function downloadArtifactArchive(
  {
    threadId,
    runId,
  }: {
    threadId: string;
    runId: string;
  },
  options?: ArtifactRequestOptions,
): Promise<ArtifactArchiveDownload> {
  return requestArtifact(
    urlOfArtifactArchive({ threadId, runId }),
    {
      method: "POST",
    },
    async (response) => {
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
    },
    options,
  );
}

export async function getArtifactArchiveManifest(
  {
    threadId,
    runId,
  }: {
    threadId: string;
    runId: string;
  },
  options?: ArtifactRequestOptions,
): Promise<ArtifactArchiveManifest> {
  return requestArtifact(
    urlOfArtifactArchive({ threadId, runId }),
    undefined,
    async (response) => {
      if (!response.ok) {
        throw new ArtifactRequestError(
          response.status,
          await readErrorDetail(response),
        );
      }
      const data = (await response.json()) as { file_count: number };
      return { fileCount: data.file_count };
    },
    options,
  );
}
