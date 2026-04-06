import { classifyVsfxArtifactPath } from "./classify";

export type VsfxSiblingPairing = {
  primary: string;
  cda: string | null;
  properties: string | null;
};

export function pairVsfxSiblingMetadata({
  openedPath,
  artifactPaths,
}: {
  openedPath: string;
  artifactPaths: string[];
}): VsfxSiblingPairing {
  const primaryMetadata = classifyVsfxArtifactPath(openedPath);

  if (primaryMetadata.kind !== "vsfx") {
    throw new Error(`Expected a .vsfx artifact path, received: ${openedPath}`);
  }

  let cdaPath: string | null = null;
  let propertiesPath: string | null = null;

  for (const artifactPath of artifactPaths) {
    const artifactMetadata = classifyVsfxArtifactPath(artifactPath);

    if (
      artifactMetadata.directory !== primaryMetadata.directory
      || artifactMetadata.basename !== primaryMetadata.basename
    ) {
      continue;
    }

    if (artifactMetadata.kind === "cda-json") {
      cdaPath = artifactPath;
      continue;
    }

    if (artifactMetadata.kind === "properties-json") {
      propertiesPath = artifactPath;
    }
  }

  return {
    primary: openedPath,
    cda: cdaPath,
    properties: propertiesPath,
  };
}
