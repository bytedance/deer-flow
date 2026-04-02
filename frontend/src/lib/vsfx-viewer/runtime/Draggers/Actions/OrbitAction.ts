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

  constructor(viewer: IViewer, callbacks: OrbitCallbacks) {
    super(viewer);
    this.beginInteractivity = callbacks.beginInteractivity;
    this.endInteractivity = callbacks.endInteractivity;
  }

  beginAction(x: number, y: number) {
    this.startPoint = { x, y };
    this.beginInteractivity();
  }

  action(x: number, y: number) {
    const params = this.getViewParams();

    if (!params) {
      return;
    }

    const viewportSize = Math.max(params.viewFieldWidth, params.viewFieldHeight, 1);
    const yaw = ((this.startPoint.x - x) * Math.PI) / viewportSize;
    const pitch = ((this.startPoint.y - y) * Math.PI) / viewportSize;
    const center = [...params.target];
    const offset = subtract(params.position, center);
    const up = normalize(params.upVector);
    const yawedOffset = rotateAroundAxis(offset, up, yaw);
    const right = normalize(cross(yawedOffset, up));
    const pitchedOffset = magnitude(right) <= EPSILON
      ? yawedOffset
      : rotateAroundAxis(yawedOffset, right, pitch);
    const nextUp = magnitude(right) <= EPSILON ? up : normalize(rotateAroundAxis(up, right, pitch));

    params.position = add(center, pitchedOffset);
    params.target = center;
    params.upVector = nextUp;
    this.startPoint = { x, y };

    this.setViewParams(params);
  }

  endAction() {
    this.endInteractivity();
  }
}

function add(left: number[], right: number[]) {
  return left.map((value, index) => value + (right[index] ?? 0));
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
