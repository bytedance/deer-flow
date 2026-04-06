import { useEffect } from "react";
import { describe, expect, test } from "vitest";

import { render, screen } from "@/test/render";

import {
  VsfxContextProvider,
  useVsfxContext,
} from "../context";

import { VsfxPropertiesWindow } from "./VsfxPropertiesWindow";

type HarnessProps = {
  primaryHandle?: string | number | null;
  properties?: unknown;
  propertiesError?: {
    code: "invalid-json" | "load-failed" | "missing";
    filepath: string;
    message: string;
  } | null;
  propertiesLoading?: boolean;
};

function StateHarness({
  primaryHandle = null,
  properties = null,
  propertiesError = null,
  propertiesLoading = false,
}: HarnessProps) {
  const { actions } = useVsfxContext();

  useEffect(() => {
    actions.setSelectedHandles(primaryHandle == null ? [] : [primaryHandle]);
    actions.setPropertiesState({
      data: properties,
      error: propertiesError,
      loading: propertiesLoading,
    });
  }, [actions, primaryHandle, properties, propertiesError, propertiesLoading]);

  return null;
}

function renderPropertiesWindow(props?: HarnessProps) {
  return render(
    <VsfxContextProvider artifactKey="assembly-a">
      <div data-testid="vsfx-viewer-root">Viewer root</div>
      <StateHarness {...props} />
      <VsfxPropertiesWindow
        containerElement={null}
        minimized={false}
        offset={{ x: 0, y: 0 }}
        onOffsetChange={() => undefined}
        onToggleMinimized={() => undefined}
      />
    </VsfxContextProvider>,
  );
}

describe("VsfxPropertiesWindow", () => {
  test("renders properties from array-based payloads keyed by handle like the cad-web sidebar source data", async () => {
    renderPropertiesWindow({
      primaryHandle: 114,
      properties: [
        {
          handle: "0",
          Weight: "248571.485",
        },
        {
          handle: "114",
          Name: "Portal column",
          Material: "Q355B",
        },
      ],
    });

    expect(await screen.findByTestId("vsfx-properties-window")).toBeInTheDocument();
    expect(screen.getByText("Handle 114")).toBeInTheDocument();
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("handle")).toBeInTheDocument();
    expect(screen.getByText("114")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Portal column")).toBeInTheDocument();
    expect(screen.getByText("Material")).toBeInTheDocument();
    expect(screen.getByText("Q355B")).toBeInTheDocument();
  });

  test("renders grouped rows for a selected part by flattening nested property objects", async () => {
    renderPropertiesWindow({
      primaryHandle: 42,
      properties: {
        byHandle: {
          42: {
            Name: "Bolt",
            Dimensions: {
              "Dimensions.Length": 25,
              "Dimensions.Width": 8,
            },
            Material: {
              Grade: "A2",
              Finish: "Zinc",
              Flags: {
                RequiresInspection: true,
              },
            },
          },
        },
      },
    });

    expect(await screen.findByTestId("vsfx-properties-window")).toBeInTheDocument();
    expect(screen.getByText("Selected properties")).toBeInTheDocument();
    expect(screen.getByText("Handle 42")).toBeInTheDocument();
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Bolt")).toBeInTheDocument();
    expect(screen.getByText("Dimensions")).toBeInTheDocument();
    expect(screen.getByText("Length")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
    expect(screen.getByText("Width")).toBeInTheDocument();
    expect(screen.getByText("Material")).toBeInTheDocument();
    expect(screen.getByText("Grade")).toBeInTheDocument();
    expect(screen.getByText("A2")).toBeInTheDocument();
    expect(screen.getByText("Flags.RequiresInspection")).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
  });

  test("renders the empty state when nothing is selected or the properties payload is unavailable", async () => {
    const { rerender } = render(
      <VsfxContextProvider artifactKey="assembly-a">
        <div data-testid="vsfx-viewer-root">Viewer root</div>
        <StateHarness primaryHandle={null} properties={null} />
        <VsfxPropertiesWindow
          containerElement={null}
          minimized={false}
          offset={{ x: 0, y: 0 }}
          onOffsetChange={() => undefined}
          onToggleMinimized={() => undefined}
        />
      </VsfxContextProvider>,
    );

    expect(await screen.findByText("Select a part to inspect its properties."))
      .toBeInTheDocument();

    rerender(
      <VsfxContextProvider artifactKey="assembly-a">
        <div data-testid="vsfx-viewer-root">Viewer root</div>
        <StateHarness
          primaryHandle={42}
          properties={{ byHandle: {} }}
        />
        <VsfxPropertiesWindow
          containerElement={null}
          minimized={false}
          offset={{ x: 0, y: 0 }}
          onOffsetChange={() => undefined}
          onToggleMinimized={() => undefined}
        />
      </VsfxContextProvider>,
    );

    expect(await screen.findByText("No properties are available for the selected part."))
      .toBeInTheDocument();
  });

  test("shows a scoped error state without unmounting the viewer root", async () => {
    renderPropertiesWindow({
      primaryHandle: 42,
      properties: { byHandle: 42 },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to display properties for the selected part.",
    );
    expect(screen.getByTestId("vsfx-viewer-root")).toBeInTheDocument();
    expect(screen.getByTestId("vsfx-properties-window")).toBeInTheDocument();
  });

  test("renders a contained scroll region for large property sets", async () => {
    renderPropertiesWindow({
      primaryHandle: 7,
      properties: {
        byHandle: {
          7: Object.fromEntries(
            Array.from({ length: 80 }, (_, index) => [
              `Metric${index}`,
              `Value ${index}`,
            ]),
          ),
        },
      },
    });

    expect(await screen.findByTestId("vsfx-properties-scroll-region")).toHaveClass(
      "min-h-0",
      "flex-1",
    );
    expect(screen.getByText("Metric79")).toBeInTheDocument();
    expect(screen.getByText("Value 79")).toBeInTheDocument();
    expect(screen.getByTestId("vsfx-properties-window")).toBeInTheDocument();
  });
});
