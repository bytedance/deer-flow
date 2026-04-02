export type ViewerBinarySource = {
  data: ArrayBuffer;
  filename: string;
};

export type ViewerProgress = {
  loaded: number;
  percent: number;
  total: number;
};

export type ViewerEventMap = {
  cancel: undefined;
  changeactivedragger: string;
  clear: undefined;
  command: { args: unknown[]; name: string };
  databasechunk: ViewerBinarySource;
  dispose: undefined;
  explode: number;
  geometryend: { filename: string };
  geometryerror: { error: Error; filename: string };
  geometryprogress: number;
  geometrystart: { filename: string };
  hide: Array<string | number>;
  initialize: undefined;
  initializeprogress: ViewerProgress;
  isolate: Array<string | number>;
  open: ViewerBinarySource;
  planeviewlabel: { axis: "x" | "y" | "z"; label: string };
  regenerateall: undefined;
  resetview: undefined;
  resize: { height: number; width: number };
  select: Array<string | number>;
  showall: undefined;
  update: undefined;
  zoom: "extents" | "selected";
};
