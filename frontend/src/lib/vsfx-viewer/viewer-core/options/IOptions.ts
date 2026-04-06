export type RGB = {
  blue: number;
  green: number;
  red: number;
};

export type IOptions = {
  antialiasing?: boolean;
  cameraAnimation?: boolean;
  cameraAxisXSpeed?: number;
  cameraAxisYSpeed?: number;
  cuttingPlaneFillColor?: RGB;
  data?: Record<string, unknown>;
  edgeModel?: boolean;
  enableGestures?: boolean;
  enableStreamingMode?: boolean;
  enableZoomWheel?: boolean;
  groundShadow?: boolean;
  memoryLimit?: number;
  reverseZoomWheel?: boolean;
  rulerUnit?: string;
  sceneGraph?: boolean;
  shadows?: boolean;
  showWCS?: boolean;
};

export type ResolvedOptions = Required<Omit<IOptions, "data">> &
  Pick<IOptions, "data">;

export function defaultOptions(): ResolvedOptions {
  return {
    antialiasing: true,
    cameraAnimation: true,
    cameraAxisXSpeed: 4,
    cameraAxisYSpeed: 1,
    cuttingPlaneFillColor: { blue: 0x00, green: 0x98, red: 0xff },
    data: undefined,
    edgeModel: true,
    enableGestures: true,
    enableStreamingMode: false,
    enableZoomWheel: true,
    groundShadow: false,
    memoryLimit: 3294967296,
    reverseZoomWheel: false,
    rulerUnit: "Default",
    sceneGraph: true,
    shadows: false,
    showWCS: true,
  };
}
