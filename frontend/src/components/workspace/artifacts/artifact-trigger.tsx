import { FilesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useMaybeSidecar } from "../sidecar/context";

import { useArtifacts } from "./context";

export const ArtifactTrigger = () => {
  const { t } = useI18n();
  const { artifacts, setOpen: setArtifactsOpen } = useArtifacts();
  const sidecar = useMaybeSidecar();

  if (!artifacts || artifacts.length === 0) {
    return null;
  }
  return (
    <Tooltip content={t.common.showArtifacts}>
      <Button
        aria-label={t.common.showArtifacts}
        className="text-muted-foreground hover:text-foreground"
        variant="ghost"
        data-testid="artifact-trigger"
        onClick={() => {
          sidecar?.close();
          setArtifactsOpen(true);
        }}
      >
        <FilesIcon />
        <span className="hidden sm:inline">{t.common.artifacts}</span>
      </Button>
    </Tooltip>
  );
};
