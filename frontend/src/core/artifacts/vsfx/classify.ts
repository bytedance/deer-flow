import type { VsfxArtifactClassification, VsfxArtifactKind } from "./types";

const VSFX_SUFFIXES: Array<{ suffix: string; kind: Exclude<VsfxArtifactKind, "other"> }> = [
  { suffix: ".properties.json", kind: "properties-json" },
  { suffix: ".cda.json", kind: "cda-json" },
  { suffix: ".vsfx", kind: "vsfx" },
];

export function classifyVsfxArtifactPath(
  filepath: string,
): VsfxArtifactClassification {
  const { directory, filename } = splitFilepath(filepath);
  const normalizedFilename = filename.toLowerCase();

  for (const { suffix, kind } of VSFX_SUFFIXES) {
    if (normalizedFilename.endsWith(suffix)) {
      return {
        kind,
        filepath,
        directory,
        basename: filename.slice(0, -suffix.length),
      };
    }
  }

  return {
    kind: "other",
    filepath,
    directory,
    basename: filename,
  };
}

function splitFilepath(filepath: string) {
  const lastSlashIndex = filepath.lastIndexOf("/");

  if (lastSlashIndex === -1) {
    return {
      directory: "",
      filename: filepath,
    };
  }

  return {
    directory: filepath.slice(0, lastSlashIndex),
    filename: filepath.slice(lastSlashIndex + 1),
  };
}
