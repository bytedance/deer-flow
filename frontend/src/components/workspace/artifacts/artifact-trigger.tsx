import { FilesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useArtifacts } from "./context";

export const ArtifactTrigger = () => {
  const { t } = useI18n();
  const { files, setOpen: setArtifactsOpen } = useArtifacts();

  if (!files || files.length === 0) {
    return null;
  }
  return (
    <Tooltip content="Show files of this conversation">
      <Button
        className="text-muted-foreground hover:text-foreground"
        variant="ghost"
        onClick={() => {
          setArtifactsOpen(true);
        }}
      >
        <FilesIcon />
        {t.common.files}
      </Button>
    </Tooltip>
  );
};
