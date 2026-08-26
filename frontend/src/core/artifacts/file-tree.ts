export type ArtifactFileTreeNode =
  | {
      type: "directory";
      name: string;
      path: string;
      children: ArtifactFileTreeNode[];
    }
  | {
      type: "file";
      name: string;
      path: string;
    };

type MutableDirectory = {
  name: string;
  path: string;
  directories: Map<string, MutableDirectory>;
  files: Map<string, string>;
};

const OUTPUT_ROOTS = [
  "/mnt/user-data/outputs/",
  "mnt/user-data/outputs/",
  "user-data/outputs/",
];

function displaySegments(path: string) {
  const normalized = path.replaceAll("\\", "/");
  const root = OUTPUT_ROOTS.find((candidate) =>
    normalized.startsWith(candidate),
  );
  const relativePath = root
    ? normalized.slice(root.length)
    : normalized.replace(/^\/+/, "");
  return relativePath.split("/").filter(Boolean);
}

function compareNames(left: { name: string }, right: { name: string }) {
  return left.name.localeCompare(right.name, "en", {
    numeric: true,
    sensitivity: "base",
  });
}

function freezeDirectory(directory: MutableDirectory): ArtifactFileTreeNode[] {
  const directories = [...directory.directories.values()]
    .sort(compareNames)
    .map<ArtifactFileTreeNode>((child) => ({
      type: "directory",
      name: child.name,
      path: child.path,
      children: freezeDirectory(child),
    }));
  const files = [...directory.files.entries()]
    .map<ArtifactFileTreeNode>(([name, path]) => ({
      type: "file",
      name,
      path,
    }))
    .sort(compareNames);
  return [...directories, ...files];
}

export function buildArtifactFileTree(
  paths: readonly string[],
): ArtifactFileTreeNode[] {
  const root: MutableDirectory = {
    name: "",
    path: "",
    directories: new Map(),
    files: new Map(),
  };

  for (const path of new Set(paths)) {
    const segments = displaySegments(path);
    const fileName = segments.pop();
    if (!fileName) continue;

    let parent = root;
    for (const segment of segments) {
      const directoryPath = parent.path ? `${parent.path}/${segment}` : segment;
      let directory = parent.directories.get(segment);
      if (!directory) {
        directory = {
          name: segment,
          path: directoryPath,
          directories: new Map(),
          files: new Map(),
        };
        parent.directories.set(segment, directory);
      }
      parent = directory;
    }
    parent.files.set(fileName, path);
  }

  return freezeDirectory(root);
}
