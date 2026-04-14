import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";
import type { UploadedFileInfo } from "../uploads/api";

const THREAD_FILE_ROOT = "/mnt/user-data/";

export interface ThreadFileTreeFolderNode {
  id: string;
  kind: "folder";
  name: string;
  path: string;
  children: ThreadFileTreeNode[];
}

export interface ThreadFileTreeFileNode {
  id: string;
  kind: "file";
  name: string;
  path: string;
  filepath: string;
  displayPath: string;
}

export type ThreadFileTreeNode =
  | ThreadFileTreeFolderNode
  | ThreadFileTreeFileNode;

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

export function getThreadFileDisplayPath(filepath: string) {
  if (filepath.startsWith(THREAD_FILE_ROOT)) {
    return filepath.slice(THREAD_FILE_ROOT.length);
  }
  return filepath.replace(/^\/+/, "");
}

export function normalizeThreadHistoryFileKey(filepath: string) {
  const displayPath = getThreadFileDisplayPath(filepath);

  if (displayPath.startsWith("outputs/")) {
    return `workspace/${displayPath.slice("outputs/".length)}`;
  }

  return displayPath;
}

function getThreadFilePathSegments(filepath: string) {
  return getThreadFileDisplayPath(filepath)
    .split("/")
    .filter(Boolean);
}

function sortThreadFileTreeNodes(
  nodes: ThreadFileTreeNode[],
): ThreadFileTreeNode[] {
  return nodes
    .map((node) => {
      if (node.kind === "folder") {
        return {
          ...node,
          children: sortThreadFileTreeNodes(node.children),
        } satisfies ThreadFileTreeFolderNode;
      }
      return node;
    })
    .sort((left, right) => {
      if (left.kind !== right.kind) {
        return left.kind === "folder" ? -1 : 1;
      }
      return left.name.localeCompare(right.name);
    });
}

export function buildThreadFileTree(files: string[]) {
  const tree: ThreadFileTreeNode[] = [];
  const folders = new Map<string, ThreadFileTreeFolderNode>();

  for (const filepath of mergeThreadFilePaths({ artifacts: files })) {
    const segments = getThreadFilePathSegments(filepath);
    if (segments.length === 0) {
      continue;
    }

    let level = tree;
    const pathParts: string[] = [];

    for (const segment of segments.slice(0, -1)) {
      pathParts.push(segment);
      const folderPath = pathParts.join("/");
      let folder = folders.get(folderPath);
      if (!folder) {
        folder = {
          id: `folder:${folderPath}`,
          kind: "folder",
          name: segment,
          path: folderPath,
          children: [],
        };
        folders.set(folderPath, folder);
        level.push(folder);
      }
      level = folder.children;
    }

    const displayPath = segments.join("/");
    const name = segments[segments.length - 1]!;
    level.push({
      id: `file:${filepath}`,
      kind: "file",
      name,
      path: displayPath,
      filepath,
      displayPath,
    });
  }

  return sortThreadFileTreeNodes(tree);
}

export function collectThreadFileTreeFolderIds(tree: ThreadFileTreeNode[]) {
  const folderIds: string[] = [];

  for (const node of tree) {
    if (node.kind !== "folder") {
      continue;
    }
    folderIds.push(node.id, ...collectThreadFileTreeFolderIds(node.children));
  }

  return folderIds;
}
