import {
  CANVAS_EVENTS,
  type IDragger,
  type IViewer,
  type ViewerInteractionEventMap,
} from "@/lib/vsfx-viewer/viewer-core";

import type { Viewer } from "../../Viewer";

import type { DragPoint } from "./Geometry";

const CLICK_DELTA = 5;
const INTERACTIVITY_FPS = 24;

export abstract class OdBaseDragger implements IDragger {
  protected autoSelect = false;
  protected canvasEvents = [...CANVAS_EVENTS];
  protected isDragging = false;
  protected mouseDownPosition: DragPoint = { x: 0, y: 0 };
  protected press = false;
  protected readonly viewer: IViewer;
  private initialized = false;

  readonly id: string;

  constructor(viewer: IViewer, id: string) {
    this.viewer = viewer;
    this.id = id;
  }

  activate() {
    void this.id;
  }

  deactivate() {
    void this.id;
  }

  initialize() {
    if (this.initialized) {
      return;
    }

    this.canvasEvents = this.canvasEvents.filter(
      (eventName) => typeof (this as Record<string, unknown>)[eventName] === "function",
    );

    for (const eventName of this.canvasEvents) {
      const handler = (
        this as Record<string, (...args: Array<unknown>) => void>
      )[eventName].bind(this);

      (this as Record<string, unknown>)[eventName] = handler;
      this.viewer.on(
        eventName as keyof ViewerInteractionEventMap,
        handler as (payload: ViewerInteractionEventMap[keyof ViewerInteractionEventMap]) => void,
      );
    }

    const runtime = this.viewer as Viewer;

    runtime.getVisualizeViewer()?.setEnableAutoSelect?.(!!this.autoSelect);
    this.initialized = true;
  }

  dispose() {
    if (!this.initialized) {
      return;
    }

    for (const eventName of this.canvasEvents) {
      this.viewer.off(
        eventName as keyof ViewerInteractionEventMap,
        (this as Record<string, (payload: unknown) => void>)[eventName],
      );
    }

    this.initialized = false;
  }

  protected click(event: MouseEvent) {
    if (!this.autoSelect) {
      return;
    }

    const relCoord = this.relativeCoords(event);
    const isNotDragging
      = Math.abs(relCoord.x - this.mouseDownPosition.x) < CLICK_DELTA
        && Math.abs(relCoord.y - this.mouseDownPosition.y) < CLICK_DELTA;

    if (!isNotDragging) {
      return;
    }

    const runtime = this.viewer as Viewer;
    const runtimeViewer = runtime.getVisualizeViewer() as {
      getEnableAutoSelect?: () => boolean;
      select?: (x1: number, y1: number, x2: number, y2: number) => void;
      unselect?: () => void;
    } | null;

    if (!(runtimeViewer?.getEnableAutoSelect?.() ?? this.autoSelect)) {
      return;
    }

    runtimeViewer?.unselect?.();
    runtimeViewer?.select?.(relCoord.x, relCoord.y, relCoord.x, relCoord.y);
    runtime.update();
    runtime.emit("select", runtime.getSelected());
  }

  protected end(x: number, y: number, absoluteX = 0, absoluteY = 0) {
    void x;
    void y;
    void absoluteX;
    void absoluteY;
  }

  protected pointercancel(event: PointerEvent) {
    if (!event.isPrimary) {
      return;
    }

    const target = this.viewer.getContainer();

    if (target instanceof HTMLCanvasElement) {
      target.dispatchEvent(new PointerEvent("pointerup", event));
      return;
    }

    this.pointerup(event);
  }

  protected pointerdown(event: PointerEvent) {
    if (!event.isPrimary || OdBaseDragger.isGestureActive) {
      return;
    }

    try {
      (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
    }
    catch {
      // noop
    }

    const relCoord = this.relativeCoords(event);
    this.isDragging = true;
    this.mouseDownPosition = { x: relCoord.x, y: relCoord.y };
    this.start(relCoord.x, relCoord.y, event.clientX, event.clientY);
    this.viewer.update();
  }

  protected pointermove(event: PointerEvent) {
    if (!event.isPrimary || OdBaseDragger.isGestureActive) {
      return;
    }

    const relCoord = this.relativeCoords(event);
    this.drag(relCoord.x, relCoord.y, event.clientX, event.clientY);

    if (this.isDragging) {
      this.viewer.update();
    }
  }

  protected pointerup(event: PointerEvent) {
    if (OdBaseDragger.needSkipPointerUp || !event.isPrimary) {
      return;
    }

    try {
      (event.target as HTMLElement).releasePointerCapture?.(event.pointerId);
    }
    catch {
      // noop
    }

    const relCoord = this.relativeCoords(event);
    this.end(relCoord.x, relCoord.y, event.clientX, event.clientY);
    this.isDragging = false;
    this.viewer.update();
  }

  protected relativeCoords(event: MouseEvent | PointerEvent): DragPoint {
    return {
      x: event.offsetX * window.devicePixelRatio,
      y: event.offsetY * window.devicePixelRatio,
    };
  }

  protected start(x: number, y: number, absoluteX = 0, absoluteY = 0) {
    void x;
    void y;
    void absoluteX;
    void absoluteY;
  }

  protected drag(x: number, y: number, absoluteX = 0, absoluteY = 0) {
    void x;
    void y;
    void absoluteX;
    void absoluteY;
  }

  protected readonly beginInteractivity = () => {
    const runtime = this.viewer as Viewer;
    const runtimeViewer = runtime.getVisualizeViewer() as {
      activeView?: {
        beginInteractivity?: (fps: number) => void;
        delete?: () => void;
      };
    } | null;
    const view = runtimeViewer?.activeView;

    if (view?.beginInteractivity) {
      view.beginInteractivity(INTERACTIVITY_FPS);
      runtime.update();
    }

    view?.delete?.();
  };

  protected readonly endInteractivity = () => {
    const runtime = this.viewer as Viewer;
    const runtimeViewer = runtime.getVisualizeViewer() as {
      activeView?: {
        delete?: () => void;
        endInteractivity?: () => void;
      };
      getActiveDevice?: () => {
        delete?: () => void;
        invalidate?: (bounds: [number, number, number, number]) => void;
      };
    } | null;
    const view = runtimeViewer?.activeView;

    if (view?.endInteractivity) {
      view.endInteractivity();

      const device = runtimeViewer?.getActiveDevice?.();
      const canvas = this.viewer.getContainer();

      if (canvas instanceof HTMLCanvasElement) {
        device?.invalidate?.([0, 0, canvas.width, canvas.height]);
      }

      device?.delete?.();
      runtime.update();
    }

    view?.delete?.();
  };

  protected static set isGestureActive(value: boolean) {
    if (OdBaseDragger._isGestureActive === value) {
      return;
    }

    OdBaseDragger._isGestureActive = value;

    if (value) {
      OdBaseDragger.needSkipPointerUp = true;
    }
  }

  protected static get isGestureActive() {
    return OdBaseDragger._isGestureActive;
  }

  static consumeNeedSkipPointerUp() {
    return OdBaseDragger.needSkipPointerUp;
  }

  private static _isGestureActive = false;

  private static _needSkipPointerUp = false;

  private static get needSkipPointerUp() {
    if (OdBaseDragger._needSkipPointerUp) {
      OdBaseDragger._needSkipPointerUp = false;
      return true;
    }

    return false;
  }

  private static set needSkipPointerUp(value: boolean) {
    OdBaseDragger._needSkipPointerUp = value;
  }
}
