import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OrbitAction } from "./Actions/OrbitAction";
import { PanAction } from "./Actions/PanAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

type ActiveMode = "none" | "orbit" | "pan";

export class OdOrbitPanDragger extends OdBaseDragger {
  private activeMode: ActiveMode = "none";
  private currentButton = -1;
  private readonly orbitAction: OrbitAction;
  private readonly panAction: PanAction;

  constructor(viewer: IViewer) {
    super(viewer, "orbit-pan");
    this.autoSelect = true;
    this.canvasEvents.push("contextmenu", "auxclick");
    this.orbitAction = new OrbitAction(viewer, {
      beginInteractivity: this.beginInteractivity,
      endInteractivity: this.endInteractivity,
    });
    this.panAction = new PanAction(viewer, {
      beginInteractivity: this.beginInteractivity,
      endInteractivity: this.endInteractivity,
    });
  }

  protected contextmenu(event: MouseEvent) {
    if (this.activeMode !== "pan") {
      return;
    }

    try {
      event.preventDefault();
      event.stopPropagation();
    }
    catch {
      // noop
    }
  }

  protected auxclick(event: MouseEvent) {
    if (event.button !== 1) {
      return;
    }

    try {
      event.preventDefault();
      event.stopPropagation();
    }
    catch {
      // noop
    }
  }

  protected mousedown(event: MouseEvent) {
    if (event.button !== 1) {
      return;
    }

    try {
      event.preventDefault();
      event.stopPropagation();
    }
    catch {
      // noop
    }
  }

  protected override pointerdown(event: PointerEvent) {
    if (!event.isPrimary || OdBaseDragger.isGestureActive) {
      return;
    }

    if (event.button === 0) {
      this.activeMode = "orbit";
    }
    else if (event.button === 1) {
      this.activeMode = "pan";

      try {
        event.preventDefault();
        event.stopPropagation();
      }
      catch {
        // noop
      }
    }
    else {
      return;
    }

    this.currentButton = event.button;

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

  protected override pointerup(event: PointerEvent) {
    if (OdBaseDragger.consumeNeedSkipPointerUp()) {
      return;
    }

    if (!event.isPrimary || event.button !== this.currentButton) {
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
    this.activeMode = "none";
    this.currentButton = -1;
    this.viewer.update();
  }

  protected start(x: number, y: number, absoluteX: number, absoluteY: number) {
    this.press = true;

    if (this.activeMode === "orbit") {
      this.orbitAction.beginAction(x, y);
      return;
    }

    if (this.activeMode === "pan") {
      this.panAction.beginAction(x, y, absoluteX, absoluteY);
    }
  }

  protected drag(x: number, y: number, absoluteX: number, absoluteY: number) {
    if (!this.press) {
      return;
    }

    if (this.activeMode === "orbit") {
      this.orbitAction.action(x, y);
      return;
    }

    if (this.activeMode === "pan") {
      this.panAction.action(x, y, absoluteX, absoluteY);
    }
  }

  protected end() {
    this.press = false;

    if (this.activeMode === "orbit") {
      this.orbitAction.endAction();
      return;
    }

    if (this.activeMode === "pan") {
      this.panAction.endAction();
    }
  }
}
