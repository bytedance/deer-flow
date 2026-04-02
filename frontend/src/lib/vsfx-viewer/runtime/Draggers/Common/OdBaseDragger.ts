import {
  CANVAS_EVENTS,
  type IDragger,
  type IViewer,
  type ViewerInteractionEventMap,
} from "@/lib/vsfx-viewer/viewer-core";

export abstract class OdBaseDragger implements IDragger {
  protected canvasEvents = [...CANVAS_EVENTS];
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
}
