import { urlOfArtifact } from "../utils";

import { classifyVsfxArtifactPath } from "./classify";
import { pairVsfxSiblingMetadata } from "./pairing";

type VsfxPanelErrorCode = "invalid-json" | "load-failed" | "missing";
type VsfxPanelKey = "cdaTree" | "primary" | "properties";

export type VsfxArtifactPanelError = {
  code: VsfxPanelErrorCode;
  filepath: string;
  message: string;
};

export type VsfxArtifactBundle = {
  primaryUrl: string | null;
  cdaTree: unknown | null;
  properties: unknown | null;
  loading: boolean;
  errors: {
    primary: VsfxArtifactPanelError | null;
    cdaTree: VsfxArtifactPanelError | null;
    properties: VsfxArtifactPanelError | null;
  };
};

export type VsfxArtifactBundleRequest = {
  cancel: () => void;
  initial: VsfxArtifactBundle;
  promise: Promise<VsfxArtifactBundle>;
};

type FetchLike = typeof fetch;

export function createInitialVsfxArtifactBundle(
  threadId: string,
  filepath: string,
  isMock = false,
): VsfxArtifactBundle {
  const classification = classifyVsfxArtifactPath(filepath);

  if (classification.kind !== "vsfx") {
    return {
      primaryUrl: null,
      cdaTree: null,
      properties: null,
      loading: false,
      errors: {
        primary: createPanelError(
          "primary",
          filepath,
          "load-failed",
          `Expected a .vsfx artifact path, received: ${filepath}`,
        ),
        cdaTree: null,
        properties: null,
      },
    };
  }

  return {
    primaryUrl: urlOfArtifact({ filepath, threadId, isMock }),
    cdaTree: null,
    properties: null,
    loading: true,
    errors: {
      primary: null,
      cdaTree: null,
      properties: null,
    },
  };
}

export function createVsfxArtifactBundleRequest(
  threadId: string,
  filepath: string,
  artifacts: string[],
  isMock = false,
  fetchImpl: FetchLike = fetch,
): VsfxArtifactBundleRequest {
  const initial = createInitialVsfxArtifactBundle(threadId, filepath, isMock);

  if (!initial.primaryUrl || initial.errors.primary) {
    return {
      cancel: () => undefined,
      initial,
      promise: Promise.resolve(initial),
    };
  }

  const controller = new AbortController();
  const pairing = pairVsfxSiblingMetadata({
    openedPath: filepath,
    artifactPaths: artifacts,
  });
  const expectedSiblingPaths = createExpectedSiblingPaths(filepath);

  const promise = Promise.all([
    loadOptionalJson({
      expectedFilepath: expectedSiblingPaths.cdaTree,
      fetchImpl,
      filepath: pairing.cda,
      isMock,
      signal: controller.signal,
      threadId,
      panel: "cdaTree",
    }),
    loadOptionalJson({
      expectedFilepath: expectedSiblingPaths.properties,
      fetchImpl,
      filepath: pairing.properties,
      isMock,
      signal: controller.signal,
      threadId,
      panel: "properties",
    }),
  ]).then(([cda, properties]) => ({
    primaryUrl: initial.primaryUrl,
    cdaTree: cda.data,
    properties: properties.data,
    loading: false,
    errors: {
      primary: null,
      cdaTree: cda.error,
      properties: properties.error,
    },
  }));

  return {
    cancel: () => {
      controller.abort();
    },
    initial,
    promise,
  };
}

export function isVsfxArtifactAbortError(error: unknown) {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

async function loadOptionalJson({
  expectedFilepath,
  fetchImpl,
  filepath,
  isMock,
  panel,
  signal,
  threadId,
}: {
  expectedFilepath: string;
  fetchImpl: FetchLike;
  filepath: string | null;
  isMock: boolean;
  panel: Exclude<VsfxPanelKey, "primary">;
  signal: AbortSignal;
  threadId: string;
}) {
  if (!filepath) {
    return {
      data: null,
      error: createPanelError(panel, expectedFilepath, "missing"),
    };
  }

  let response: Response;

  try {
    const url = urlOfArtifact({ filepath, threadId, isMock });
    response = await fetchImpl(url, { signal });
  }
  catch (error) {
    if (isVsfxArtifactAbortError(error)) {
      throw error;
    }

    return {
      data: null,
      error: createPanelError(panel, filepath, "load-failed"),
    };
  }

  if (!response.ok) {
    return {
      data: null,
      error: createPanelError(
        panel,
        filepath,
        response.status === 404 ? "missing" : "load-failed",
        response.status === 404
          ? `Missing ${panelLabel(panel)} sibling artifact: ${filepath}`
          : `Failed to load ${panelLabel(panel)} sibling artifact: ${filepath}`,
      ),
    };
  }

  const content = await response.text();

  try {
    return {
      data: JSON.parse(content) as unknown,
      error: null,
    };
  }
  catch {
    return {
      data: null,
      error: createPanelError(panel, filepath, "invalid-json"),
    };
  }
}

function createPanelError(
  panel: VsfxPanelKey,
  filepath: string,
  code: VsfxPanelErrorCode,
  message = defaultPanelErrorMessage(panel, filepath, code),
): VsfxArtifactPanelError {
  return {
    code,
    filepath,
    message,
  };
}

function defaultPanelErrorMessage(
  panel: VsfxPanelKey,
  filepath: string,
  code: VsfxPanelErrorCode,
) {
  if (code === "missing") {
    return `Missing ${panelLabel(panel)} artifact: ${filepath}`;
  }

  if (code === "invalid-json") {
    return `Malformed ${panelLabel(panel)} JSON: ${filepath}`;
  }

  return `Failed to load ${panelLabel(panel)} artifact: ${filepath}`;
}

function panelLabel(panel: VsfxPanelKey) {
  switch (panel) {
    case "cdaTree":
      return "construct tree";
    case "properties":
      return "properties";
    default:
      return "primary VSFX";
  }
}

function createExpectedSiblingPaths(filepath: string) {
  const classification = classifyVsfxArtifactPath(filepath);
  const prefix = classification.directory ? `${classification.directory}/` : "";

  return {
    cdaTree: `${prefix}${classification.basename}.cda.json`,
    properties: `${prefix}${classification.basename}.Properties.json`,
  };
}
