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
import { useCanvas } from "@/core/canvas/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import {
  ArtifactFileDetail,
  ArtifactFileList,
  useArtifacts,
} from "../artifacts";
import { CanvasPanel, useCanvasContext } from "../canvas";
import { useThread } from "../messages/context";

// 布局常量（所有模式都包含3个panel）
const CLOSE_MODE = { chat: 100, artifacts: 0, canvas: 0 };
const ARTIFACTS_OPEN_MODE = { chat: 60, artifacts: 40, canvas: 0 };
const CANVAS_OPEN_MODE = { chat: 50, artifacts: 0, canvas: 50 };

const ChatBox: React.FC<{ children: React.ReactNode; threadId: string }> = ({
  children,
  threadId,
}) => {
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

  const { open: canvasOpen, setOpen: setCanvasOpen, setCanvas } = useCanvasContext();

  // 加载 canvas 数据
  const { canvas } = useCanvas(threadId, !!threadId);

  // 同步 canvas 数据到 context
  useEffect(() => {
    if (canvas) {
      setCanvas(canvas);
    }
  }, [canvas, setCanvas]);

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

  // 计算布局：Canvas 优先于 Artifacts
  const layout = useMemo(() => {
    if (canvasOpen) {
      return CANVAS_OPEN_MODE;
    }
    if (artifactPanelOpen) {
      return ARTIFACTS_OPEN_MODE;
    }
    return CLOSE_MODE;
  }, [canvasOpen, artifactPanelOpen]);

  // 当 Canvas 打开时关闭 Artifacts（新增扩展逻辑）
  useEffect(() => {
    if (canvasOpen && artifactsOpen) {
      setArtifactsOpen(false);
    }
  }, [canvasOpen, artifactsOpen, setArtifactsOpen]);

  // 当 Artifacts 打开时关闭 Canvas（新增扩展逻辑）
  useEffect(() => {
    if (artifactPanelOpen && canvasOpen) {
      setCanvasOpen(false);
    }
  }, [artifactPanelOpen, canvasOpen, setCanvasOpen]);

  // 设置布局（扩展：支持 canvas）
  useEffect(() => {
    if (layoutRef.current) {
      layoutRef.current.setLayout(layout);
    }
  }, [layout]);

  return (
    <ResizablePanelGroup
      id={`${resizableIdBase}-panels`}
      orientation="horizontal"
      defaultLayout={{ chat: 100, artifacts: 0, canvas: 0 }}
      groupRef={layoutRef}
    >
      {/* Chat Panel - 保持不变 */}
      <ResizablePanel className="relative" defaultSize={100} id="chat">
        {children}
      </ResizablePanel>

      {/* Artifacts Handle - 保持不变 */}
      <ResizableHandle
        id={`${resizableIdBase}-separator`}
        className={cn(
          "opacity-33 hover:opacity-100",
          !artifactPanelOpen && !canvasOpen && "pointer-events-none opacity-0",
        )}
      />

      {/* Artifacts Panel - 保持不变 */}
      <ResizablePanel
        className={cn(
          "transition-all duration-300 ease-in-out",
          !artifactsOpen && "opacity-0",
        )}
        id="artifacts"
      >
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
      </ResizablePanel>

      {/* Canvas Handle - 新增扩展 */}
      <ResizableHandle
        id={`${resizableIdBase}-canvas-separator`}
        className={cn(
          "opacity-33 hover:opacity-100",
          !canvasOpen && "pointer-events-none opacity-0",
        )}
      />

      {/* Canvas Panel - 新增扩展 */}
      <ResizablePanel
        className={cn(
          "transition-all duration-300 ease-in-out",
          !canvasOpen && "opacity-0",
        )}
        id="canvas"
        defaultSize={0}
      >
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
      </ResizablePanel>
    </ResizablePanelGroup>
  );
};

export { ChatBox };
