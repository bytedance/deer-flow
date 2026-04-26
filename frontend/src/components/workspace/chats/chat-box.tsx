import { FilesIcon, XIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GroupImperativeHandle } from "react-resizable-panels";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import {
  ArtifactFileDetail,
  ArtifactFileList,
  useArtifacts,
} from "../artifacts";
import {
  CanvasPanel,
  CanvasProvider,
  useCanvasContext,
} from "../canvas";
import { useThread } from "../messages/context";

const CLOSE_MODE = { chat: 100, artifacts: 0 };
const OPEN_MODE = { chat: 60, artifacts: 40 };
const CANVAS_OPEN_MODE = { chat: 50, canvas: 50 };

// Canvas 面板内部组件
const CanvasPanelWrapper: React.FC = () => {
  const { open: canvasOpen, setOpen: setCanvasOpen } = useCanvasContext();

  return (
    <div
      className={cn(
        "h-full transition-transform duration-300 ease-in-out",
        canvasOpen ? "translate-x-0" : "translate-x-full",
      )}
    >
      <div className="relative flex size-full flex-col">
        <div className="absolute top-1 right-1 z-30">
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => {
              setCanvasOpen(false);
            }}
          >
            <XIcon />
          </Button>
        </div>
        <CanvasPanel />
      </div>
    </div>
  );
};

// 内层面板组件 - 处理 artifacts 和 canvas
const InnerPanels: React.FC<{
  children: React.ReactNode;
  threadId: string;
}> = ({ children, threadId }) => {
  const { thread } = useThread();
  const pathname = usePathname();
  const threadIdRef = useRef(threadId);
  const layoutRef = useRef<GroupImperativeHandle>(null);

  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    select: selectArtifact,
    deselect,
    selectedArtifact,
  } = useArtifacts();

  const { open: canvasOpen, setOpen: setCanvasOpen } = useCanvasContext();

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);
  useEffect(() => {
    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
    }

    // Update artifacts from the current thread
    setArtifacts(thread.values.artifacts);

    if (
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
      autoSelectFirstArtifact
    ) {
      if (thread?.values?.artifacts?.length > 0) {
        setAutoSelectFirstArtifact(false);
        selectArtifact(thread.values.artifacts[0]!);
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
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts]);

  const resizableIdBase = useMemo(() => {
    return pathname.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  }, [pathname]);

  // 计算布局：canvas 优先于 artifacts
  const layout = useMemo(() => {
    if (canvasOpen) {
      return CANVAS_OPEN_MODE;
    }
    if (artifactPanelOpen) {
      return OPEN_MODE;
    }
    return CLOSE_MODE;
  }, [canvasOpen, artifactPanelOpen]);

  useEffect(() => {
    if (layoutRef.current) {
      layoutRef.current.setLayout(layout);
    }
  }, [layout]);

  // 当 canvas 打开时关闭 artifacts，反之亦然
  useEffect(() => {
    if (canvasOpen && artifactsOpen) {
      setArtifactsOpen(false);
    }
  }, [canvasOpen, artifactsOpen, setArtifactsOpen]);

  useEffect(() => {
    if (artifactPanelOpen && canvasOpen) {
      setCanvasOpen(false);
    }
  }, [artifactPanelOpen, canvasOpen, setCanvasOpen]);

  return (
    <ResizablePanelGroup
      id={`${resizableIdBase}-panels`}
      orientation="horizontal"
      defaultLayout={{ chat: 100, artifacts: 0 }}
      groupRef={layoutRef}
    >
      <ResizablePanel className="relative" defaultSize={100} id="chat">
        {children}
      </ResizablePanel>
      <ResizableHandle
        id={`${resizableIdBase}-separator`}
        className={cn(
          "opacity-33 hover:opacity-100",
          !artifactPanelOpen && !canvasOpen && "pointer-events-none opacity-0",
        )}
      />
      <ResizablePanel
        className={cn(
          "transition-all duration-300 ease-in-out",
          !artifactsOpen && !canvasOpen && "opacity-0",
        )}
        id={canvasOpen ? "canvas" : "artifacts"}
      >
        {canvasOpen ? (
          <CanvasPanelWrapper />
        ) : (
          <div
            className={cn(
              "h-full p-4 transition-transform duration-300 ease-in-out",
              artifactPanelOpen ? "translate-x-0" : "translate-x-full",
            )}
          >
            {selectedArtifact ? (
              <ArtifactFileDetail
                className="size-full"
                filepath={selectedArtifact}
                threadId={threadId}
              />
            ) : (
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
                {thread.values.artifacts?.length === 0 ? (
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
                        files={thread.values.artifacts ?? []}
                        threadId={threadId}
                      />
                    </main>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </ResizablePanel>
    </ResizablePanelGroup>
  );
};

const ChatBox: React.FC<{ children: React.ReactNode; threadId: string }> = ({
  children,
  threadId,
}) => {
  return (
    <CanvasProvider>
      <InnerPanels threadId={threadId}>{children}</InnerPanels>
    </CanvasProvider>
  );
};

export { ChatBox };
