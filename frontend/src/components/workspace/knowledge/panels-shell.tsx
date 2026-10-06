"use client";

import { PanelLeftOpenIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { Layout, PanelImperativeHandle } from "react-resizable-panels";
import { Toaster } from "sonner";

import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { KB_TOASTER_ID } from "./kb-toast";

const LEFT_PANEL_ID = "kb-list";

// Mirrors the app sidebar's collapse timing (ui/sidebar.tsx uses
// transition-[width] duration-200 ease-linear). Panel widths here are inline
// flex-grow values on the panel's OUTER div — react-resizable-panels renders
// it as id={panel id} and drops our className onto a child instead, so the
// transition targets #kb-list through a data attribute on the shell. Armed
// only for programmatic folds: a live transition would lag gutter drags.
const FOLD_ANIMATION_MS = 200;

// Fold phases are driven by INTENT plus the transition's own completion
// event — the app sidebar's design, which runs its collapse as pure CSS with
// zero per-frame JS. Watching the width with a ResizeObserver instead fired
// on every frame of every transition and drag, and even with bailouts that
// per-frame work roughened both; transitionend lands exactly when the motion
// does, and costs nothing in between.

export interface KnowledgePanelsControls {
  /** Fold the list column from inside its own header (expanded state only). */
  collapseLeft: () => void;
  /**
   * Restore control for the middle column's header row. Always provided —
   * it is a hover overlay the consumer lays over the start of the library
   * name (the workspace header's DF hover-swap pattern) — but its visibility
   * is gated by scoped CSS on the shell's fold-state attribute: revealed only
   * once the fold has settled. Gating through the attribute keeps THIS node's
   * identity stable across every phase change, so a fold settle patches a few
   * classNames instead of re-rendering both consumer subtrees (a traced ~130ms
   * re-render riding the fold's last frame was the end-of-collapse jitter).
   */
  listToggle: ReactNode;
}

/**
 * Three-column shell of the knowledge page (spec §5.2) built on
 * react-resizable-panels: both gutters drag to resize with pixel min/max
 * guards, and the left kb list folds push-style (drag past its min width or
 * click its header button → width 0; the middle header's restore button brings
 * it back). Neither control floats over the content column — the old absolute
 * mid-height handle sat on top of whichever document row happened to be
 * centred. The restore button must exist independently of the collapse one
 * because drag-to-edge folds the column without ever touching a button.
 * Button-triggered folds animate with the app sidebar's 200ms ease-linear
 * curve (on flex-grow, armed only for that fold); drags stay transition-free.
 * Every fold phase (hidden content, restore overlay, armed transition, pin
 * release) lands when the transition itself reports done.
 * The middle column keeps its 320px minimum; the chat column keeps a 320px
 * floor too so the composer row (deep-research switch + model selector + send
 * button) never wraps at the panel's narrowest drag position. Extreme narrow
 * widths fall back to horizontal scrolling on an overlay ScrollArea (百科 Tab
 * 容器同款隐式滑条：只滚动时浮现、停 2s 淡出、不占布局高度) instead of the old
 * native overflow-x-auto bar spanning the columns, and never crush columns.
 * The Group carries min-w-[52rem] because the library
 * always fits panels into the container width — without it, a viewport
 * narrower than the sum of all panel minimums silently violates every
 * minSize.
 */
export function KnowledgePanelsShell({
  left,
  middle,
  right,
}: {
  left: (controls: KnowledgePanelsControls) => ReactNode;
  middle: (controls: KnowledgePanelsControls) => ReactNode;
  right: ReactNode;
}) {
  const { t } = useI18n();
  const tk = t.knowledge;
  const leftPanelRef = useRef<PanelImperativeHandle | null>(null);
  const asideRef = useRef<HTMLElement | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);
  // Intent-driven fold phase: "folding" from the click until the CSS
  // transition itself reports done (or the drag settles), never from
  // per-frame measurement.
  const [phase, setPhase] = useState<"expanded" | "folding" | "collapsed">("expanded");
  // The direction of the current programmatic fold; picks the content fade
  // curve. Width phases alone cannot tell the two mid-fades apart.
  const [collapsing, setCollapsing] = useState(false);
  // Pinning the content to its width at the fold's start keeps it clipped
  // instead of reflowed while the column resizes (Chinese text otherwise
  // wraps per character) — like the app sidebar, whose content keeps a
  // constant width and slides. The pin survives BOTH directions and is
  // released from the width clock once the panel has grown back to it:
  // dropping it earlier squeezed the content back into its compressed state.
  const [frozenWidth, setFrozenWidth] = useState<number | null>(null);
  // Last measured expanded width — the fallback pin source when a fold came
  // from drag-to-edge (which never pins) and the list is restored later.
  const lastWidthRef = useRef(0);
  // True while a programmatic fold owns the phase; drag layout events are
  // ignored until the transition settles.
  const inFlightRef = useRef(false);
  const settleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Called exactly once per fold, when the CSS transition reports done (or
  // the safety timer elapses if the event never fires — interrupted
  // transitions emit nothing). The library's own layout verdict decides the
  // resting phase — pixels are only the fallback — so a settle that races a
  // paused/throttled transition cannot misread an in-flight width; for
  // unfolds that also releases the width pin, since the panel being back at
  // rest IS the arrival the pin was waiting for.
  const settleFold = useCallback(() => {
    // Idempotent: the attribute marks an in-flight fold; whichever settle path
    // arrives first removes it, later ones bail.
    if (!shellRef.current?.hasAttribute("data-fold-animating")) return;
    if (settleTimerRef.current) {
      clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
    }
    shellRef.current?.removeAttribute("data-fold-animating");
    inFlightRef.current = false;
    // In the real DOM the library's layout verdict is authoritative (pixels
    // can lag a throttled transition); without a mounted panel (tests) the
    // resting width decides instead.
    const panelEl = document.getElementById(LEFT_PANEL_ID);
    const collapsedNow = panelEl
      ? !!leftPanelRef.current?.isCollapsed()
      : (asideRef.current?.offsetWidth ?? 0) <= 0;
    if (collapsedNow) {
      setPhase("collapsed");
    } else {
      const w = asideRef.current?.offsetWidth ?? 0;
      if (w > 0) lastWidthRef.current = w;
      setPhase("expanded");
      setFrozenWidth(null);
    }
  }, []);

  // Arm the flex-grow transition by attribute on the shell div, and wire its
  // completion: transitionend on the sized element, backed by a timer in case
  // the event is swallowed. Registration is deferred to a microtask: the
  // collapse()/expand() state updates commit their render (rule + retarget)
  // inside the same synchronous block, and listening before that lets the
  // browser start AND finish committing the transition within one task —
  // which ate the event (and squeezed the visible motion with it).
  // The event-driven settle is further deferred one task: transitionend fires
  // on the animation's very last frame, and settling synchronously there made
  // the full-page phase re-render contend with that frame — the fold's
  // end-of-motion hitch. The safety-timer path lands after the motion
  // anyway, so it settles directly.
  const armFoldTransition = useCallback(() => {
    inFlightRef.current = true;
    shellRef.current?.setAttribute("data-fold-animating", "true");
    if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
    settleTimerRef.current = setTimeout(settleFold, FOLD_ANIMATION_MS + 200);
    queueMicrotask(() => {
      document
        .getElementById(LEFT_PANEL_ID)
        ?.addEventListener("transitionend", () => setTimeout(settleFold, 0), {
          once: true,
        });
    });
  }, [settleFold]);
  useEffect(
    () => () => {
      if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
    },
    [],
  );

  const collapsedEnough = phase === "collapsed";
  const foldAnimating = phase === "folding";

  const collapseLeft = useCallback(() => {
    if (asideRef.current) {
      setFrozenWidth(asideRef.current.offsetWidth || lastWidthRef.current || null);
    }
    setCollapsing(true);
    setPhase("folding");
    armFoldTransition();
    leftPanelRef.current?.collapse();
  }, [armFoldTransition]);
  const expandLeft = useCallback(() => {
    // A fold that came from drag-to-edge never pinned; fall back to the
    // last measured expanded width. Release happens in settleFold once the
    // unfold has genuinely arrived.
    setFrozenWidth((prev) => prev ?? lastWidthRef.current ?? null);
    setCollapsing(false);
    setPhase("folding");
    armFoldTransition();
    leftPanelRef.current?.expand();
  }, [armFoldTransition]);
  // Drag path: fires on pointer release, so it never runs per drag frame.
  const handleLayoutChanged = useCallback((layout: Layout) => {
    if (inFlightRef.current) return;
    setPhase(layout[LEFT_PANEL_ID] === 0 ? "collapsed" : "expanded");
  }, []);

  // The restore control is a hover overlay over the library name's start —
  // the workspace header's DF hover-swap pattern. Absolutely positioned (zero
  // layout advance), and gated by scoped CSS on the shell's fold-state
  // attribute rather than by mounting/unmounting: a mount at the collapse's
  // settle changed this memo's inputs, re-rendered both consumer subtrees
  // (~130ms) right on the fold's last frame — the end-of-collapse jitter.
  // Single visible state: a precise-hit opaque chip — a semi-transparent
  // backdrop read as smudged text under the button.
  const listToggleNode = useMemo(
    () => (
      <div
        className="kb-restore-overlay absolute top-1/2 left-2 z-10 -translate-y-1/2 opacity-0 transition-opacity duration-150"
        data-testid="kb-list-toggle-overlay"
      >
        <Button
          aria-label={tk.expandKbList}
          className="text-muted-foreground hover:text-foreground border-border bg-background size-6 shrink-0 border shadow-xs"
          data-testid="kb-list-toggle"
          size="icon"
          variant="ghost"
          onClick={expandLeft}
        >
          <PanelLeftOpenIcon className="size-4" />
        </Button>
      </div>
    ),
    [tk, expandLeft],
  );

  // The heavy render-prop subtrees are memoized so a fold phase change
  // (click, settle) re-renders only the shell's own chrome. A traced
  // full-page re-render at the settle cost ~130ms on the main thread and
  // landed right on the fold's last frame — the end-of-fold hitch. The
  // memo inputs stay referentially equal across a collapse settle, so that
  // settle now patches a few classNames and nothing else.
  const leftNode = useMemo(
    () => left({ collapseLeft, listToggle: listToggleNode }),
    [left, collapseLeft, listToggleNode],
  );
  const middleNode = useMemo(
    () => middle({ collapseLeft, listToggle: listToggleNode }),
    [middle, collapseLeft, listToggleNode],
  );

  return (
    <div
      className="relative size-full min-h-0"
      data-kb-fold-state={phase}
      data-testid="knowledge-panels-shell"
      ref={shellRef}
    >
      {/* The sized element is the panel's outer div (id=kb-list, inline
          flex-grow) — unreachable by className, hence a scoped rule gated by
          the shell's data-fold-animating attribute. The restore overlay is
          CSS-gated by the fold state for the same reason its reveal must not
          ride a re-render: mounting it at the settle re-rendered the consumer
          subtrees on the fold's last frame — the end-of-collapse jitter. */}
      <style>{`
        [data-fold-animating] #${LEFT_PANEL_ID} { transition: flex-grow ${FOLD_ANIMATION_MS}ms linear; }
        .kb-restore-overlay { visibility: hidden; pointer-events: none; }
        [data-kb-fold-state="collapsed"] .kb-restore-overlay { visibility: visible; pointer-events: auto; }
        [data-kb-fold-state="collapsed"] .kb-restore-overlay:hover,
        [data-kb-fold-state="collapsed"] .kb-restore-overlay:focus-within { opacity: 1; }
      `}</style>
      {/* 窄视口横滚（2026-09-08 隐式滑条化）：外壳原生 overflow-x-auto 退役——
          老滑块常驻底部横跨文档栏+会话栏；改 overlay ScrollArea（horizontal +
          type="scroll" + 停 2s 淡出）。Viewport 内 Radix 测量 div 默认 auto 高会
          让 PanelGroup 的 size-full 百分比失解析（高度链断），故钉 h-full。 */}
      <ScrollArea
        className="size-full [&_[data-slot=scroll-area-viewport]>div]:h-full"
        horizontal
        scrollHideDelay={2000}
        type="scroll"
      >
      <ResizablePanelGroup
        className="size-full min-w-[52rem] min-h-0"
        orientation="horizontal"
        onLayoutChanged={handleLayoutChanged}
      >
        <ResizablePanel
          className="min-h-0"
          collapsible
          collapsedSize={0}
          defaultSize={224}
          id={LEFT_PANEL_ID}
          maxSize={360}
          minSize={176}
          panelRef={leftPanelRef}
        >
          <aside
            aria-hidden={collapsedEnough}
            className={cn(
              "size-full overflow-hidden border-r",
              collapsedEnough && "pointer-events-none opacity-0",
              // Collapsing: stay legible for most of the fold, then fade out
              // over its second half. The opacity-0 TARGET is armed here too —
              // arming it only at the settle snapped it in one frame (the
              // transition class leaves at the same time) — the collapse's
              // end jitter. Expanding: fade in over the full curve.
              foldAnimating &&
                collapsing &&
                "transition-opacity duration-100 delay-100 ease-[cubic-bezier(0.4,0,1,1)] opacity-0",
              foldAnimating && !collapsing && "transition-opacity duration-200 ease-linear",
            )}
            ref={asideRef}
          >
            {/* Frozen at the fold's start so the column clips the content
                instead of squeezing it into per-character wrapping. */}
            <div
              className="h-full"
              style={frozenWidth !== null ? { width: frozenWidth } : undefined}
            >
              {leftNode}
            </div>
          </aside>
        </ResizablePanel>
        <ResizableHandle
          className={cn(
            "hover:bg-accent w-0.5 transition-colors",
            // Collapsed: interactivity off, paint ON (2026-09-03). Fading this
            // gutter out left its 2px layout slot as a strip of bare
            // bg-background between the app sidebar's border-r and the middle
            // column, so the document table's left edge — and with it the
            // header hairline and a selected row's background — began 2px
            // short of the divider, while the right gutter (section border-r +
            // a painted handle) sat flush against its own. Painting it also
            // makes the collapsed divider the same 2.67px bar the expanded
            // state already drew (aside border-r + handle), so the fold's last
            // frame has nothing to snap back: the fade this replaced needed a
            // matching in-flight transition to hide a vanish that no longer
            // happens.
            collapsedEnough && "pointer-events-none",
          )}
          disabled={collapsedEnough}
        />
        <ResizablePanel className="min-h-0 min-w-0" id="documents" minSize={320}>
          <section className="relative size-full border-r">
            {middleNode}
            {/* 知识库中栏专属通知面（2026-09-08）：sonner 全局 Toaster 是视口 fixed
                右下角，在本页正好压住会话栏输入框；改在中栏内挂 absolute 的 scoped
                Toaster（sonner 2.x 按 toasterId 分流，与全局侧互不重复），通知落在
                「知识库详情这栏」的右下角。宽度随栏收（中栏最窄 320 < toast 默认
                356），绝不溢出到会话栏。 */}
            <Toaster
              closeButton
              id={KB_TOASTER_ID}
              position="bottom-right"
              style={
                {
                  position: "absolute",
                  "--width": "min(356px, calc(100% - 32px))",
                } as CSSProperties
              }
            />
          </section>
        </ResizablePanel>
        <ResizableHandle className="hover:bg-accent w-0.5 transition-colors" />
        <ResizablePanel
          className="min-h-0"
          defaultSize={352}
          id="chat"
          maxSize={560}
          minSize={320}
        >
          <aside className="size-full">{right}</aside>
        </ResizablePanel>
      </ResizablePanelGroup>
      </ScrollArea>
    </div>
  );
}
