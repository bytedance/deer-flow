"use client";

import { BrainIcon } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tooltip } from "@/components/workspace/tooltip";
import { SessionMemoryPanel } from "@/components/workspace/settings/session-memory-panel";
import { env } from "@/env";

export function MemoryTrigger({ threadId }: { threadId: string }) {
  const [open, setOpen] = useState(false);

  if (env.NEXT_PUBLIC_MEMORY_UI_ENABLED === "false") {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Tooltip content="Memory">
        <DialogTrigger asChild>
          <Button
            className="text-muted-foreground hover:text-foreground"
            variant="ghost"
          >
            <BrainIcon />
          </Button>
        </DialogTrigger>
      </Tooltip>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Session Memory</DialogTitle>
        </DialogHeader>
        <div className="mt-4">
          <SessionMemoryPanel initialThreadId={threadId} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
