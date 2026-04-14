import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";
import type { UploadedFileInfo } from "../uploads/api";

export function urlOfArtifact({
  filepath,
  threadId,
  download = false,
  isMock = false,
}: {
  filepath: string;
  threadId: string;
  download?: boolean;
  isMock?: boolean;
}) {
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
}

export function extractArtifactsFromThread(thread: AgentThread) {
  return thread.values.artifacts ?? [];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${absolutePath}`;
}

export function extractUploadVirtualPaths(
  uploads: UploadedFileInfo[] | null | undefined,
) {
  const seen = new Set<string>();
  const paths: string[] = [];

  for (const upload of uploads ?? []) {
    for (const path of [
      upload.virtual_path,
      upload.markdown_virtual_path,
    ] as const) {
      if (!path || seen.has(path)) {
        continue;
      }
      seen.add(path);
      paths.push(path);
    }
  }

  return paths;
}

export function mergeThreadFilePaths({
  uploads = [],
  artifacts = [],
}: {
  uploads?: string[];
  artifacts?: string[];
}) {
  const seen = new Set<string>();
  const files: string[] = [];

  for (const path of [...uploads, ...artifacts]) {
    if (!path || seen.has(path)) {
      continue;
    }
    seen.add(path);
    files.push(path);
  }

  return files;
}
