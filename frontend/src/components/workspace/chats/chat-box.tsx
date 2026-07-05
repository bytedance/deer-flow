import { FilesIcon, XIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import {
  ArtifactFileDetail,
  ArtifactFileList,
  useArtifacts,
} from "../artifacts";
import { useThread } from "../messages/context";
import { SidecarPanel, useMaybeSidecar } from "../sidecar";

const RIGHT_PANEL_ANIMATION_MS = 280;

type RightPanelKind = "sidecar" | "artifacts";

const ChatBox: React.FC<{ children: React.ReactNode; threadId: string }> = ({
  children,
  threadId,
}) => {
  const { thread } = useThread();
  const pathname = usePathname();
  const threadIdRef = useRef(threadId);

  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    select: selectArtifact,
    deselect,
    selectedArtifact,
  } = useArtifacts();
  const sidecar = useMaybeSidecar();
  const sidecarOpen = sidecar?.open ?? false;

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);
  useEffect(() => {
    const threadArtifacts = Array.isArray(thread.values.artifacts)
      ? thread.values.artifacts
      : undefined;

    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
      setArtifacts([]);
    }

    // Update artifacts from the current thread
    if (threadArtifacts) {
      setArtifacts(threadArtifacts);
    }

    // DO NOT automatically deselect the artifact when switching threads, because the artifacts auto discovering is not work now.
    // if (
    //   selectedArtifact &&
    //   !thread.values.artifacts?.includes(selectedArtifact)
    // ) {
    //   deselect();
    // }

    if (
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
      autoSelectFirstArtifact
    ) {
      if (threadArtifacts && threadArtifacts.length > 0) {
        setAutoSelectFirstArtifact(false);
        selectArtifact(threadArtifacts[0]!);
      }
    }
  }, [
    threadId,
    autoSelectFirstArtifact,
    deselect,
    selectArtifact,
    selectedArtifact,
    setArtifacts,
    thread.values.artifacts,
  ]);

  const artifactPanelOpen = useMemo(() => {
    if (sidecarOpen) {
      return false;
    }
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts, sidecarOpen]);

  const activeRightPanel: RightPanelKind | null = sidecarOpen
    ? "sidecar"
    : artifactPanelOpen
      ? "artifacts"
      : null;
  const rightPanelOpen = activeRightPanel !== null;
  const [renderedRightPanel, setRenderedRightPanel] =
    useState<RightPanelKind | null>(activeRightPanel);

  const resizableIdBase = useMemo(() => {
    return pathname.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  }, [pathname]);

  useEffect(() => {
    if (activeRightPanel) {
      setRenderedRightPanel(activeRightPanel);
      return;
    }

    const timeout = window.setTimeout(() => {
      setRenderedRightPanel(null);
    }, RIGHT_PANEL_ANIMATION_MS);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [activeRightPanel]);

  useEffect(() => {
    if (sidecarOpen && artifactsOpen) {
      setArtifactsOpen(false);
    }
  }, [artifactsOpen, setArtifactsOpen, sidecarOpen]);

  return (
    <div
      id={`${resizableIdBase}-panels`}
      className={cn(
        "[container-type:inline-size] grid size-full min-h-0 transition-[grid-template-columns] duration-[280ms] ease-out motion-reduce:transition-none",
        rightPanelOpen
          ? "grid-cols-[minmax(0,1fr)_1px_minmax(0,40%)]"
          : "grid-cols-[minmax(0,1fr)_0px_0px]",
      )}
    >
      <div className="relative min-h-0 min-w-0" id="chat">
        {children}
      </div>
      <div
        id={`${resizableIdBase}-separator`}
        aria-hidden="true"
        className={cn(
          "bg-border opacity-33 transition-opacity duration-200 ease-out motion-reduce:transition-none",
          !rightPanelOpen && "pointer-events-none opacity-0",
        )}
      />
      <aside
        aria-hidden={!rightPanelOpen}
        className={cn(
          "min-h-0 min-w-0 overflow-hidden transition-opacity duration-[280ms] ease-out motion-reduce:transition-none",
          !rightPanelOpen && "pointer-events-none opacity-0",
        )}
        id="artifacts"
      >
        <div
          className={cn(
            "ml-auto h-full w-[40cqw] transition-opacity duration-[280ms] ease-out motion-reduce:transition-none",
            renderedRightPanel === "sidecar" ? "p-0" : "p-4",
            rightPanelOpen ? "opacity-100" : "opacity-0",
          )}
        >
          {renderedRightPanel === "sidecar" ? (
            <SidecarPanel />
          ) : renderedRightPanel === "artifacts" && selectedArtifact ? (
            <ArtifactFileDetail
              className="size-full"
              filepath={selectedArtifact}
              threadId={threadId}
            />
          ) : renderedRightPanel === "artifacts" ? (
            <div className="relative flex size-full justify-center">
              <div className="absolute top-1 right-1 z-30">
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => {
                    setArtifactsOpen(false);
                  }}
                >
                  <XIcon />
                </Button>
              </div>
              {artifacts.length === 0 ? (
                <ConversationEmptyState
                  icon={<FilesIcon />}
                  title="No artifact selected"
                  description="Select an artifact to view its details"
                />
              ) : (
                <div className="flex size-full max-w-(--container-width-sm) flex-col justify-center p-4 pt-8">
                  <header className="shrink-0">
                    <h2 className="text-lg font-medium">Artifacts</h2>
                  </header>
                  <main className="min-h-0 grow">
                    <ArtifactFileList
                      className="max-w-(--container-width-sm) p-4 pt-12"
                      files={artifacts}
                      threadId={threadId}
                    />
                  </main>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
};

export { ChatBox };
