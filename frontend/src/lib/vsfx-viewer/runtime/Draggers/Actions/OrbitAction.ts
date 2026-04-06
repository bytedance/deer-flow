import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OdaGeAction } from "../Common/OdaGeAction";

const EPSILON = 1e-6;

type OrbitCallbacks = {
  beginInteractivity: () => void;
  endInteractivity: () => void;
};

export class OrbitAction extends OdaGeAction {
  private readonly beginInteractivity: () => void;
  private readonly endInteractivity: () => void;
  private startPoint = { x: 0, y: 0 };
  private viewCenter = [0, 0, 0];

  constructor(viewer: IViewer, callbacks: OrbitCallbacks) {
    super(viewer);
    this.beginInteractivity = callbacks.beginInteractivity;
    this.endInteractivity = callbacks.endInteractivity;
  }

  beginAction(x: number, y: number) {
    const params = this.getViewParams();

    this.viewCenter = this.getOrbitCenter(params?.target ?? [0, 0, 0]);
    this.startPoint = { x, y };
    this.beginInteractivity();
  }

  action(x: number, y: number) {
    const view = this.getViewer()?.activeView;

    if (!view) {
      return;
    }

    const corners = view.vportRect ?? [0, 0, view.viewFieldWidth, view.viewFieldHeight];
    const viewportSize = Math.max(
      Math.abs((corners[2] ?? 0) - (corners[0] ?? 0)),
      Math.abs((corners[3] ?? 0) - (corners[1] ?? 0)),
      1,
    );
    const distX = ((this.startPoint.x - x) * Math.PI) / viewportSize;
    const distY = ((this.startPoint.y - y) * Math.PI) / viewportSize;
    const xOrbit = distY;
    const yOrbit = distX;
    const params = {
      perspective: view.perspective,
      position: [...view.viewPosition],
      target: [...view.viewTarget],
      upVector: [...view.upVector],
      viewFieldHeight: view.viewFieldHeight,
      viewFieldWidth: view.viewFieldWidth,
    };

    view.delete?.();

    this.startPoint = { x, y };

    const sideVector = normalize(cross(params.upVector, subtract(params.target, params.position)));

    if (xOrbit !== 0) {
      params.position = rotateAroundAxisWithCenter(
        params.position,
        sideVector,
        this.viewCenter,
        -xOrbit,
      );
      params.target = rotateAroundAxisWithCenter(
        params.target,
        sideVector,
        this.viewCenter,
        -xOrbit,
      );
      params.upVector = normalize(cross(subtract(params.target, params.position), sideVector));
    }

    if (yOrbit !== 0) {
      const zAxis = [0, 0, 1];

      params.position = rotateAroundAxisWithCenter(
        params.position,
        zAxis,
        this.viewCenter,
        yOrbit,
      );
      params.target = rotateAroundAxisWithCenter(
        params.target,
        zAxis,
        this.viewCenter,
        yOrbit,
      );

      const rotatedSide = rotateAroundAxis(sideVector, zAxis, yOrbit);
      params.upVector = normalize(cross(subtract(params.target, params.position), rotatedSide));
    }

    this.setViewParams(params);
  }

  endAction() {
    this.endInteractivity();
  }
}

function subtract(left: number[], right: number[]) {
  return left.map((value, index) => value - (right[index] ?? 0));
}

function cross(left: number[], right: number[]) {
  return [
    (left[1] ?? 0) * (right[2] ?? 0) - (left[2] ?? 0) * (right[1] ?? 0),
    (left[2] ?? 0) * (right[0] ?? 0) - (left[0] ?? 0) * (right[2] ?? 0),
    (left[0] ?? 0) * (right[1] ?? 0) - (left[1] ?? 0) * (right[0] ?? 0),
  ];
}

function dot(left: number[], right: number[]) {
  return left.reduce((total, value, index) => total + value * (right[index] ?? 0), 0);
}

function magnitude(vector: number[]) {
  return Math.hypot(...vector);
}

function normalize(vector: number[]) {
  const length = magnitude(vector);

  if (length <= EPSILON) {
    return [0, 1, 0];
  }

  return vector.map((value) => value / length);
}

function rotateAroundAxis(vector: number[], axis: number[], angle: number) {
  if (Math.abs(angle) <= EPSILON) {
    return [...vector];
  }

  const unitAxis = normalize(axis);
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const crossProduct = cross(unitAxis, vector);
  const projection = unitAxis.map((value) => value * dot(unitAxis, vector) * (1 - cos));

  return vector.map(
    (value, index) => value * cos + (crossProduct[index] ?? 0) * sin + (projection[index] ?? 0),
  );
}

function rotateAroundAxisWithCenter(
  point: number[],
  axis: number[],
  center: number[],
  angle: number,
) {
  const relative = subtract(point, center);
  const rotated = rotateAroundAxis(relative, axis, angle);

  return rotated.map((value, index) => value + (center[index] ?? 0));
}
