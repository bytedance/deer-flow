import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";

import {
  ModelPicker,
  ModelPickerContent,
  ModelPickerTrigger,
} from "@/components/workspace/model-picker-content";
import { useAuth } from "@/core/auth/AuthProvider";
import { type Model } from "@/core/models/types";
import { useModelFavorites } from "@/core/models/use-model-favorites";

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: rs.fn(),
}));

rs.mock("@/core/models/use-model-favorites", () => ({
  useModelFavorites: rs.fn(),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    changeLocale: rs.fn(),
    t: {
      modelPicker: {
        title: "Choose a model",
        favorites: "Favorites",
        otherModels: "Other models",
        noModels: "No models available",
        favoriteModel: (displayName: string, name: string) =>
          `Favorite ${displayName} (${name})`,
        sessionOnly: "Favorites are stored for this session only.",
      },
    },
  }),
}));

const MODELS: readonly Model[] = [
  {
    id: "one",
    name: "provider/alpha",
    model: "alpha-api",
    display_name: "Shared label",
    description: "Fast general model",
  },
  {
    id: "two",
    name: ' provider/"beta" ',
    model: "beta-api",
    display_name: "Shared label",
    description: "Careful reasoning model",
  },
  {
    id: "three",
    name: "provider/gamma",
    model: "gamma-api",
    display_name: "Gamma",
    description: null,
  },
];

const mockedUseAuth = rs.mocked(useAuth);
const mockedUseModelFavorites = rs.mocked(useModelFavorites);
const setFavorite = rs.fn();

let authUser: { id: string } | null;
let authLoading: boolean;
let favoriteNames: readonly string[];
let persistence: "local" | "memory";

function installHookState() {
  mockedUseAuth.mockImplementation(
    () =>
      ({
        user: authUser,
        isAuthenticated: authUser !== null,
        isLoading: authLoading,
        logout: rs.fn(),
        refreshUser: rs.fn(),
        applyUser: rs.fn(),
      }) as ReturnType<typeof useAuth>,
  );
  mockedUseModelFavorites.mockImplementation((userId) => ({
    names: userId === null ? [] : favoriteNames,
    persistence: userId === null ? "memory" : persistence,
    canEdit: userId !== null,
    setFavorite,
  }));
}

interface PickerHarnessProps {
  models?: readonly Model[];
  selectedModelName?: string;
  onModelSelect?: (name: string) => void;
  initiallyOpen?: boolean;
}

function StatefulPicker({
  models = MODELS,
  selectedModelName = MODELS[0]?.name,
  onModelSelect = () => undefined,
  initiallyOpen = true,
}: PickerHarnessProps) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <ModelPicker open={open} onOpenChange={setOpen}>
      <ModelPickerTrigger asChild>
        <button type="button">Current model</button>
      </ModelPickerTrigger>
      <ModelPickerContent
        open={open}
        models={models}
        selectedModelName={selectedModelName}
        onModelSelect={onModelSelect}
      />
    </ModelPicker>
  );
}

function ControlledPicker({
  open,
  models = MODELS,
  selectedModelName = MODELS[0]?.name,
  onModelSelect = () => undefined,
}: PickerHarnessProps & { open: boolean }) {
  return (
    <ModelPicker open={open}>
      <ModelPickerTrigger asChild>
        <button type="button">Current model</button>
      </ModelPickerTrigger>
      <ModelPickerContent
        open={open}
        models={models}
        selectedModelName={selectedModelName}
        onModelSelect={onModelSelect}
      />
    </ModelPicker>
  );
}

function modelButtons() {
  return Array.from(
    document.querySelectorAll<HTMLButtonElement>(
      'button[data-model-picker-option="true"]',
    ),
  );
}

function favoriteButton(model: Model) {
  return screen.getByRole("button", {
    name: `Favorite ${model.display_name} (${model.name})`,
  });
}

beforeEach(() => {
  authUser = { id: "alice" };
  authLoading = false;
  favoriteNames = [MODELS[1]!.name];
  persistence = "local";
  setFavorite.mockReset();
  installHookState();
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("ModelPickerContent anchored selection", () => {
  it("opens without a modal overlay and exposes inline favorite actions", async () => {
    render(<StatefulPicker />);

    const dialog = await screen.findByRole("dialog", {
      name: "Choose a model",
    });
    expect(document.querySelector('[data-slot="dialog-overlay"]')).toBeNull();
    expect(dialog.className).toContain("w-72");
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByText("Fast general model")).toBeNull();
    expect(favoriteButton(MODELS[0]!)).not.toBeNull();
    expect(
      screen.queryByRole("button", { name: "Manage favorites" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
  });

  it("renders favorites first and preserves API order inside each group", async () => {
    render(<StatefulPicker />);

    const favorites = await screen.findByRole("group", { name: "Favorites" });
    const others = screen.getByRole("group", { name: "Other models" });
    expect(
      within(favorites).getByText("beta-api").closest("li"),
    ).not.toBeNull();
    expect(
      within(others)
        .getAllByRole("listitem")
        .map((row) => row.textContent),
    ).toEqual([
      expect.stringContaining("alpha-api"),
      expect.stringContaining("gamma-api"),
    ]);
  });

  it("omits the empty favorites heading without filtering the model list", async () => {
    favoriteNames = [];
    render(<StatefulPicker />);

    await screen.findByRole("dialog");
    expect(screen.queryByText("Favorites")).toBeNull();
    expect(screen.getByText("Other models")).not.toBeNull();
    expect(modelButtons()).toHaveLength(MODELS.length);
  });

  it("shows the no-model state", async () => {
    render(<ControlledPicker open models={[]} />);
    expect(await screen.findByText("No models available")).not.toBeNull();
  });

  it("selects duplicate-label models by their untouched names", async () => {
    const onModelSelect = rs.fn();
    render(<StatefulPicker onModelSelect={onModelSelect} />);

    await screen.findByRole("dialog");
    const shared = modelButtons().filter((button) =>
      button.textContent?.includes("Shared label"),
    );
    fireEvent.click(shared[0]!);
    fireEvent.click(shared[1]!);
    expect(onModelSelect.mock.calls).toEqual([
      [MODELS[1]!.name],
      [MODELS[0]!.name],
    ]);
  });

  it("marks the current model without nesting the favorite button", async () => {
    render(<StatefulPicker selectedModelName={MODELS[1]!.name} />);

    const current = await screen.findByRole("button", {
      name: `Shared label (${MODELS[1]!.name})`,
    });
    expect(current.getAttribute("aria-current")).toBe("true");
    expect(current.getAttribute("data-current-model")).toBe("true");
    expect(within(current).queryByRole("button")).toBeNull();
    expect(current.parentElement?.contains(favoriteButton(MODELS[1]!))).toBe(
      true,
    );
  });

  it("focuses the current model and moves between rows with arrows", async () => {
    render(<StatefulPicker />);
    const current = await screen.findByRole("button", {
      name: `Shared label (${MODELS[0]!.name})`,
    });
    const gamma = screen.getByRole("button", {
      name: `Gamma (${MODELS[2]!.name})`,
    });

    await waitFor(() => expect(document.activeElement).toBe(current));
    fireEvent.keyDown(current, { key: "ArrowDown" });
    expect(document.activeElement).toBe(gamma);
    fireEvent.keyDown(gamma, { key: "ArrowUp" });
    expect(document.activeElement).toBe(current);
  });

  it("moves from favorite stars to adjacent model rows with arrows", async () => {
    render(<StatefulPicker />);
    const betaStar = await screen.findByRole("button", {
      name: `Favorite ${MODELS[1]!.display_name} (${MODELS[1]!.name})`,
    });
    const alpha = screen.getByRole("button", {
      name: `Shared label (${MODELS[0]!.name})`,
    });
    const gamma = screen.getByRole("button", {
      name: `Gamma (${MODELS[2]!.name})`,
    });

    betaStar.focus();
    fireEvent.keyDown(betaStar, { key: "ArrowDown" });
    expect(document.activeElement).toBe(alpha);

    betaStar.focus();
    fireEvent.keyDown(betaStar, { key: "ArrowUp" });
    expect(document.activeElement).toBe(gamma);
  });
});

describe("ModelPickerContent favorite actions", () => {
  it("updates a favorite without selecting a model or closing the picker", async () => {
    const onModelSelect = rs.fn();
    render(<StatefulPicker onModelSelect={onModelSelect} />);
    const betaStar = await screen.findByRole("button", {
      name: `Favorite ${MODELS[1]!.display_name} (${MODELS[1]!.name})`,
    });

    expect(betaStar.getAttribute("aria-pressed")).toBe("true");
    expect(betaStar.className).toContain("size-8");
    fireEvent.click(betaStar);

    expect(setFavorite).toHaveBeenCalledWith(MODELS[1]!.name, false);
    expect(onModelSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).not.toBeNull();
  });

  it("restores focus to the same star after favorite regrouping", async () => {
    favoriteNames = [];
    const { rerender } = render(<ControlledPicker open />);
    const betaStar = await screen.findByRole("button", {
      name: `Favorite ${MODELS[1]!.display_name} (${MODELS[1]!.name})`,
    });
    betaStar.focus();
    fireEvent.click(betaStar);

    favoriteNames = [MODELS[1]!.name];
    rerender(<ControlledPicker open />);
    await waitFor(() =>
      expect(document.activeElement).toBe(favoriteButton(MODELS[1]!)),
    );
  });

  it("preserves the user's focus during an external favorite regroup", async () => {
    favoriteNames = [];
    const { rerender } = render(
      <ControlledPicker open selectedModelName={MODELS[0]!.name} />,
    );
    const beta = await screen.findByRole("button", {
      name: `Shared label (${MODELS[1]!.name})`,
    });
    beta.focus();
    expect(document.activeElement).toBe(beta);

    favoriteNames = [MODELS[1]!.name];
    rerender(<ControlledPicker open selectedModelName={MODELS[0]!.name} />);

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", {
          name: `Shared label (${MODELS[1]!.name})`,
        }),
      ),
    );

    favoriteButton(MODELS[1]!).focus();
    favoriteNames = [];
    rerender(<ControlledPicker open selectedModelName={MODELS[0]!.name} />);

    await waitFor(() =>
      expect(document.activeElement).toBe(favoriteButton(MODELS[1]!)),
    );
  });

  it("hides stars when signed out and disables them during auth refresh", async () => {
    authUser = null;
    const { rerender } = render(<ControlledPicker open />);
    await screen.findByRole("dialog");
    expect(
      screen.queryByRole("button", { name: /Favorite Shared label/ }),
    ).toBeNull();

    authUser = { id: "alice" };
    authLoading = true;
    rerender(<ControlledPicker open />);
    expect(favoriteButton(MODELS[0]!).hasAttribute("disabled")).toBe(true);
  });

  it("revalidates loading and a same-reference catalog in the latest handler", async () => {
    const mutableModels = [...MODELS];
    const { rerender } = render(
      <ControlledPicker open models={mutableModels} />,
    );
    const alphaStar = await screen.findByRole("button", {
      name: `Favorite ${MODELS[0]!.display_name} (${MODELS[0]!.name})`,
    });

    authLoading = true;
    rerender(<ControlledPicker open models={mutableModels} />);
    alphaStar.removeAttribute("disabled");
    fireEvent.click(alphaStar);
    expect(setFavorite).not.toHaveBeenCalled();

    authLoading = false;
    rerender(<ControlledPicker open models={mutableModels} />);
    const connectedStar = favoriteButton(MODELS[0]!);
    mutableModels.splice(0, 1);
    fireEvent.click(connectedStar);
    expect(setFavorite).not.toHaveBeenCalled();
  });

  it("only announces persistence when storage falls back to memory", async () => {
    const { rerender } = render(<ControlledPicker open />);
    await screen.findByRole("dialog");
    expect(screen.queryByRole("status")).toBeNull();

    persistence = "memory";
    rerender(<ControlledPicker open />);
    expect(screen.getByRole("status").textContent).toBe(
      "Favorites are stored for this session only.",
    );
  });
});

describe("ModelPickerContent popover lifecycle", () => {
  it("focuses the current model on every closed-to-open edge", async () => {
    const { rerender } = render(
      <ControlledPicker open selectedModelName={MODELS[2]!.name} />,
    );
    const current = await screen.findByRole("button", {
      name: `Gamma (${MODELS[2]!.name})`,
    });
    await waitFor(() => expect(document.activeElement).toBe(current));

    rerender(
      <ControlledPicker open={false} selectedModelName={MODELS[2]!.name} />,
    );
    screen.getByRole("button", { name: "Current model" }).focus();
    rerender(<ControlledPicker open selectedModelName={MODELS[2]!.name} />);

    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", {
          name: `Gamma (${MODELS[2]!.name})`,
        }),
      ),
    );
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    render(<StatefulPicker />);
    await screen.findByRole("dialog");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Current model" }),
    );
  });
});
