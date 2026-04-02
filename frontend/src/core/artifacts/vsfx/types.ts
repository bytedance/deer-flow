export type VsfxArtifactKind =
  | "vsfx"
  | "cda-json"
  | "properties-json"
  | "other";

export type VsfxArtifactClassification = {
  kind: VsfxArtifactKind;
  filepath: string;
  directory: string;
  basename: string;
};
