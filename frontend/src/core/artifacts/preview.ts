export function isArtifactPreviewSupported({
  language,
  isWriteFile,
}: {
  language: string | undefined;
  isWriteFile: boolean;
}) {
  if (language === "markdown") {
    return true;
  }

  if (language === "html") {
    return !isWriteFile;
  }

  return false;
}
