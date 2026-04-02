import {
  Options,
  type IViewer,
  type ViewerBinarySource,
  type ViewerEventMap,
} from "@/lib/vsfx-viewer/viewer-core";

import { getVisualizeAssetPaths, type VisualizeAssetPaths } from "./asset-paths";
import { viewerCommands } from "./Commands";
import { viewerComponents } from "./Components";
import { viewerDraggers } from "./Draggers";
import { LoaderFactory } from "./Loaders/LoaderFactory";
import { loadVisualizeLibrary, type VisualizeProgressState } from "./utils";

type EventListener<TPayload> = (payload: TPayload) => void;

export type VisualizeBackend = {
  clearSelected?: () => void;
  clearSlices?: () => void;
  clear?: () => void;
  collect?: () => void;
  dispose?: () => void;
  explode?: (index?: number) => void;
  k3DViewBack?: () => void;
  k3DViewBottom?: () => void;
  k3DViewFront?: () => void;
  k3DViewLeft?: () => void;
  k3DViewRight?: () => void;
  k3DViewSW?: () => void;
  k3DViewTop?: () => void;
  getSelected?: () => Array<string | number>;
  hideSelected?: () => void;
  isolateSelected?: () => void;
  measureLine?: () => void;
  parseVsfx?: (data: Uint8Array) => unknown;
  planeViewX?: () => void;
  planeViewY?: () => void;
  planeViewZ?: () => void;
  regenerateAll?: () => void;
  render?: () => void;
  resetView?: () => void;
  resize?: () => void;
  setActiveDragger?: (name: string) => void;
  setSelected?: (handles: Array<string | number>) => void;
  showAll?: () => void;
  syncView?: () => void;
  update?: () => void;
  zoomToExtents?: () => void;
  zoomToSelected?: () => void;
};

export type CreateVisualizeViewerInput = {
  container: HTMLElement;
  visualizeLibrary: unknown;
  wasmUrl: string;
};

export type ViewerDependencies = {
  createVisualizeViewer?: (input: CreateVisualizeViewerInput) => VisualizeBackend;
  loadVisualizeLibrary?: (options: {
    onProgress?: (state: VisualizeProgressState) => void;
    scriptUrl?: string;
    wasmUrl?: string;
  }) => Promise<unknown>;
};

export type ViewerInitializeOptions = {
  onProgress?: (state: VisualizeProgressState) => void;
};

export type ViewerOptions = {
  assetPaths?: VisualizeAssetPaths;
  container: HTMLElement;
  dependencies?: ViewerDependencies;
  options?: ConstructorParameters<typeof Options>[0];
};

export class Viewer implements IViewer {
  private activeDraggerName = "orbit-pan";
  private readonly assetPaths: VisualizeAssetPaths;
  private readonly componentDisposers: Array<() => void> = [];
  private readonly container: HTMLElement;
  private readonly dependencies: ViewerDependencies;
  private initialized = false;
  private readonly listeners = new Map<
    keyof ViewerEventMap,
    Set<EventListener<ViewerEventMap[keyof ViewerEventMap]>>
  >();
  private readonly options: Options;
  private visualizeBackend: VisualizeBackend | null = null;
  private visualizeLibrary: unknown = null;

  constructor({ assetPaths, container, dependencies, options }: ViewerOptions) {
    this.assetPaths = assetPaths ?? getVisualizeAssetPaths();
    this.container = container;
    this.dependencies = dependencies ?? {};
    this.options = new Options(options);
  }

  clearSlices() {
    this.visualizeBackend?.clearSlices?.();
  }

  dispose() {
    for (const dispose of this.componentDisposers.splice(0)) {
      dispose();
    }
    this.visualizeBackend?.dispose?.();
    this.visualizeBackend = null;
    this.visualizeLibrary = null;
    this.initialized = false;
    this.emit("dispose", undefined);
  }

  emit<TName extends keyof ViewerEventMap>(
    eventName: TName,
    payload: ViewerEventMap[TName],
  ) {
    const listeners = this.listeners.get(eventName);

    if (!listeners) {
      return;
    }

    for (const listener of listeners) {
      listener(payload);
    }
  }

  executeCommand(name: string, ...args: unknown[]) {
    const command = viewerCommands.getCommand(name);

    if (!command) {
      throw new Error(`Unknown viewer command: ${name}`);
    }

    const result = command(this, ...args);
    this.emit("command", { args, name });

    return result;
  }

  getCommandNames() {
    return viewerCommands.getCommandNames();
  }

  getContainer() {
    return this.container;
  }

  getDraggerNames() {
    return viewerDraggers.getDraggerNames();
  }

  getOptions() {
    return this.options.value;
  }

  getSelected() {
    return this.executeCommand("getSelected") as Array<string | number>;
  }

  getVisualizeViewer() {
    return this.visualizeBackend;
  }

  async initialize({ onProgress }: ViewerInitializeOptions = {}) {
    if (this.initialized) {
      return this;
    }

    const visualizeLibrary = await (this.dependencies.loadVisualizeLibrary ??
      loadVisualizeLibrary)({
      onProgress: (state) => {
        onProgress?.(state);
        this.emit("initializeprogress", state);
      },
      scriptUrl: this.assetPaths.scriptUrl,
      wasmUrl: this.assetPaths.wasmUrl,
    });

    this.visualizeLibrary = visualizeLibrary;
    this.visualizeBackend = (this.dependencies.createVisualizeViewer ??
      defaultCreateVisualizeViewer)({
      container: this.container,
      visualizeLibrary,
      wasmUrl: this.assetPaths.wasmUrl,
    });
    this.primeVisualizeBackend();

    this.installComponents();
    this.setActiveDragger(this.activeDraggerName);
    this.initialized = true;
    this.emit("initialize", undefined);

    return this;
  }

  on<TName extends keyof ViewerEventMap>(
    eventName: TName,
    listener: (payload: ViewerEventMap[TName]) => void,
  ) {
    const existing = this.listeners.get(eventName) ?? new Set();
    existing.add(listener as EventListener<ViewerEventMap[keyof ViewerEventMap]>);
    this.listeners.set(eventName, existing);

    return () => {
      existing.delete(
        listener as EventListener<ViewerEventMap[keyof ViewerEventMap]>,
      );
    };
  }

  async open(input: ViewerBinarySource) {
    const loader = LoaderFactory.create(input.filename, {
      emit: (eventName, payload) => {
        this.emit(eventName, payload);
      },
      getVisualizeViewer: () => this.visualizeBackend as Record<string, unknown> | null,
    });

    await loader.load(input);
    this.primeVisualizeBackend();
    this.emit("open", input);
  }

  render() {
    this.visualizeBackend?.render?.();
  }

  resize() {
    const bounds = this.container.getBoundingClientRect();
    this.visualizeBackend?.resize?.();
    this.emit("resize", {
      height: bounds.height,
      width: bounds.width,
    });
  }

  setActiveDragger(name = "orbit-pan") {
    const provider = viewerDraggers.getProvider(name);

    if (!provider) {
      throw new Error(`Unknown dragger: ${name}`);
    }

    provider(this).activate();
    this.activeDraggerName = name;
    this.emit("changeactivedragger", name);
  }

  update() {
    this.emit("update", undefined);
  }

  private installComponents() {
    for (const name of viewerComponents.getComponentNames()) {
      const installer = viewerComponents.getInstaller(name);

      if (!installer) {
        continue;
      }

      if (name === "gesture-manager" && !this.getOptions().enableGestures) {
        continue;
      }

      if (name === "zoom-wheel" && !this.getOptions().enableZoomWheel) {
        continue;
      }

      const dispose = installer(this);

      if (typeof dispose === "function") {
        this.componentDisposers.push(dispose);
      }
    }
  }

  private primeVisualizeBackend() {
    const backend = this.visualizeBackend;

    if (!backend) {
      return;
    }

    backend.syncView?.call(backend);
    backend.resize?.call(backend);
    backend.update?.call(backend);
    backend.render?.call(backend);
  }
}

function defaultCreateVisualizeViewer({ container, visualizeLibrary }: CreateVisualizeViewerInput) {
  const candidate = visualizeLibrary as {
    Viewer?: {
      create?: () => void;
    };
    canvas?: HTMLCanvasElement;
    createViewer?: () => VisualizeBackend;
    getViewer?: () => VisualizeBackend;
    viewer?: VisualizeBackend;
  };

  if (
    candidate.Viewer &&
    typeof candidate.Viewer.create === "function" &&
    typeof candidate.getViewer === "function"
  ) {
    const canvas = requireCanvasElement(container);

    prepareCanvas(canvas);
    candidate.canvas = canvas;
    candidate.Viewer.create();

    const viewer = candidate.getViewer();
    const backend = createCanvasAwareVisualizeBackend(viewer, canvas);

    backend.resize?.();

    return backend;
  }

  if (typeof candidate.createViewer === "function") {
    return candidate.createViewer();
  }

  if (typeof candidate.getViewer === "function") {
    return candidate.getViewer();
  }

  if (candidate.viewer) {
    return candidate.viewer;
  }

  throw new Error("Visualize.js library did not expose a supported viewer factory");
}

function createCanvasAwareVisualizeBackend(
  viewer: VisualizeBackend,
  canvas: HTMLCanvasElement,
): VisualizeBackend {
  const resize = viewer.resize as
    | ((a: number, b: number, c: number, d: number) => void)
    | undefined;

  viewer.resize = () => {
    prepareCanvas(canvas);
    resize?.call(viewer, 0, canvas.width, canvas.height, 0);
  };

  return viewer;
}

function prepareCanvas(canvas: HTMLCanvasElement) {
  if (canvas.style.width === "" && canvas.style.height === "") {
    canvas.style.width = "100%";
    canvas.style.height = "100%";
  }

  const width = canvas.clientWidth || canvas.width || 1;
  const height = canvas.clientHeight || canvas.height || 1;
  const pixelRatio =
    typeof window !== "undefined" && Number.isFinite(window.devicePixelRatio)
      ? window.devicePixelRatio
      : 1;

  canvas.width = Math.max(1, Math.round(width * pixelRatio));
  canvas.height = Math.max(1, Math.round(height * pixelRatio));
}

function requireCanvasElement(element: HTMLElement): HTMLCanvasElement {
  if (element instanceof HTMLCanvasElement) {
    return element;
  }

  throw new Error("Visualize.js requires an HTMLCanvasElement container");
}
