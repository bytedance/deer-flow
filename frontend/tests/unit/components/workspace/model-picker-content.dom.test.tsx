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

import { Dialog } from "@/components/ui/dialog";
import { ModelPickerContent } from "@/components/workspace/model-picker-content";
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
        description: "Search for and select a model.",
        manageFavorites: "Manage favorites",
        done: "Done",
        favorites: "Favorites",
        otherModels: "Other models",
        search: "Search models",
        noResults: "No matching models",
        noModels: "No models available",
        favoriteModel: (displayName: string, name: string) =>
          `Favorite ${displayName} (${name})`,
        localOnly: "Favorites are stored in this browser.",
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
    <Dialog open={open} onOpenChange={setOpen}>
      <ModelPickerContent
        open={open}
        models={models}
        selectedModelName={selectedModelName}
        onModelSelect={onModelSelect}
      />
    </Dialog>
  );
}

function ControlledPicker({
  open,
  models = MODELS,
  selectedModelName = MODELS[0]?.name,
  onModelSelect = () => undefined,
}: PickerHarnessProps & { open: boolean }) {
  return (
    <Dialog open={open}>
      <ModelPickerContent
        open={open}
        models={models}
        selectedModelName={selectedModelName}
        onModelSelect={onModelSelect}
      />
    </Dialog>
  );
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

describe("ModelPickerContent selection mode", () => {
  it("renders non-empty favorite and other groups in API order", async () => {
    render(<StatefulPicker />);

    expect(await screen.findByText("Favorites")).not.toBeNull();
    expect(screen.getByText("Other models")).not.toBeNull();
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      expect.stringContaining("beta-api"),
      expect.stringContaining("alpha-api"),
      expect.stringContaining("gamma-api"),
    ]);
  });

  it("omits empty group headings, including when there are zero favorites", async () => {
    favoriteNames = [];
    render(<StatefulPicker />);

    await screen.findByRole("option", { name: /alpha-api/i });
    expect(screen.queryByText("Favorites")).toBeNull();
    expect(screen.getByText("Other models")).not.toBeNull();
  });

  it("searches model name, display name, and API model without cmdk reordering", async () => {
    render(<StatefulPicker />);
    const search = await screen.findByRole("combobox", {
      name: "Choose a model",
    });

    fireEvent.change(search, { target: { value: "provider/gamma" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option").textContent).toContain("Gamma");

    fireEvent.change(search, { target: { value: "Shared label" } });
    expect(screen.getAllByRole("option")).toHaveLength(2);

    fireEvent.change(search, { target: { value: "beta-api" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option").textContent).toContain("beta-api");
  });

  it("shows distinct no-model and no-result empty states", async () => {
    const { rerender } = render(<ControlledPicker open models={[]} />);
    expect(await screen.findByText("No models available")).not.toBeNull();

    rerender(<ControlledPicker open models={MODELS} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "not-present" },
    });
    expect(screen.getByText("No matching models")).not.toBeNull();
  });

  it("keeps original names for cmdk values, React selection, and duplicate display labels", async () => {
    const onModelSelect = rs.fn();
    render(<StatefulPicker onModelSelect={onModelSelect} />);

    const shared = await screen.findAllByText("Shared label");
    const betaOption = shared[0]!.closest('[role="option"]')!;
    const alphaOption = shared[1]!.closest('[role="option"]')!;
    expect(betaOption.getAttribute("data-value")).toBe(
      JSON.stringify(MODELS[1]!.name),
    );
    expect(alphaOption.getAttribute("data-value")).toBe(
      JSON.stringify(MODELS[0]!.name),
    );

    fireEvent.click(betaOption);
    fireEvent.click(alphaOption);
    expect(onModelSelect.mock.calls).toEqual([
      [MODELS[1]!.name],
      [MODELS[0]!.name],
    ]);
  });

  it("marks the current model with a non-interactive check", async () => {
    render(<StatefulPicker selectedModelName={MODELS[1]!.name} />);

    const current = (await screen.findByText("beta-api")).closest<HTMLElement>(
      '[role="option"]',
    )!;
    expect(current.querySelector('[data-current-model="true"]')).not.toBeNull();
    expect(within(current).queryByRole("button")).toBeNull();
    expect(current.querySelector("svg")?.getAttribute("aria-hidden")).toBe(
      "true",
    );
  });

  it("highlights the first rendered match after query changes", async () => {
    render(<StatefulPicker selectedModelName={MODELS[2]!.name} />);
    const search = await screen.findByRole("combobox");

    expect(
      screen
        .getByText("gamma-api")
        .closest('[role="option"]')
        ?.getAttribute("data-selected"),
    ).toBe("true");
    fireEvent.change(search, { target: { value: "Shared label" } });

    const options = screen.getAllByRole("option");
    expect(options[0]?.textContent).toContain("beta-api");
    expect(options[0]?.getAttribute("data-selected")).toBe("true");
    expect(options[1]?.getAttribute("data-selected")).toBe("false");
  });

  it("preserves a visible highlight when favorites reorder without a query change", async () => {
    favoriteNames = [];
    const { rerender } = render(<ControlledPicker open />);
    const search = await screen.findByRole("combobox");
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(
      screen
        .getByText("beta-api")
        .closest('[role="option"]')
        ?.getAttribute("data-selected"),
    ).toBe("true");

    favoriteNames = [MODELS[1]!.name];
    rerender(<ControlledPicker open />);

    expect(screen.getAllByRole("option")[0]?.textContent).toContain("beta-api");
    expect(
      screen
        .getByText("beta-api")
        .closest('[role="option"]')
        ?.getAttribute("data-selected"),
    ).toBe("true");
  });
});

describe("ModelPickerContent favorite management", () => {
  it("keeps the toolbar outside cmdk so Enter cannot select a model", async () => {
    const onModelSelect = rs.fn();
    render(<StatefulPicker onModelSelect={onModelSelect} />);
    const manage = await screen.findByRole("button", {
      name: "Manage favorites",
    });
    manage.focus();

    const defaultAllowed = fireEvent.keyDown(manage, {
      key: "Enter",
      code: "Enter",
    });
    // happy-dom does not synthesize a button click after keyboard activation,
    // so reproduce the browser default action only when no ancestor canceled it.
    if (defaultAllowed) {
      manage.click();
    }
    expect(await screen.findByRole("button", { name: "Done" })).not.toBeNull();
    expect(onModelSelect).not.toHaveBeenCalled();
  });

  it("uses stable API-order rows and star buttons only update favorites", async () => {
    const onModelSelect = rs.fn();
    render(<StatefulPicker onModelSelect={onModelSelect} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Manage favorites" }),
    );
    const search = await screen.findByRole("searchbox", {
      name: "Search models",
    });
    await waitFor(() => expect(document.activeElement).toBe(search));

    const rows = screen.getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("alpha-api"),
      expect.stringContaining("beta-api"),
      expect.stringContaining("gamma-api"),
    ]);
    const betaStar = screen
      .getAllByRole("button")
      .find(
        (button) =>
          button.getAttribute("aria-label") ===
          `Favorite ${MODELS[1]!.display_name} (${MODELS[1]!.name})`,
      )!;
    expect(betaStar.getAttribute("aria-pressed")).toBe("true");
    expect(betaStar.className).toContain("size-11");
    expect(betaStar.querySelector("svg")?.getAttribute("aria-hidden")).toBe(
      "true",
    );

    fireEvent.mouseDown(betaStar);
    fireEvent.click(betaStar);
    expect(setFavorite).toHaveBeenCalledWith(MODELS[1]!.name, false);
    expect(onModelSelect).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(search);
    expect(
      screen.getAllByRole("listitem").map((row) => row.textContent),
    ).toEqual(rows.map((row) => row.textContent));
    expect(screen.getByRole("dialog")).not.toBeNull();
  });

  it("preserves the query across manage and Done, then restores the current highlight", async () => {
    render(<StatefulPicker selectedModelName={MODELS[1]!.name} />);
    const selectSearch = await screen.findByRole("combobox");
    fireEvent.change(selectSearch, { target: { value: "Shared label" } });
    fireEvent.click(screen.getByRole("button", { name: "Manage favorites" }));

    const manageSearch = await screen.findByRole("searchbox", {
      name: "Search models",
    });
    expect((manageSearch as HTMLInputElement).value).toBe("Shared label");
    await waitFor(() => expect(document.activeElement).toBe(manageSearch));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    const restoredSearch = await screen.findByRole("combobox");
    expect((restoredSearch as HTMLInputElement).value).toBe("Shared label");
    await waitFor(() => expect(document.activeElement).toBe(restoredSearch));
    expect(
      screen
        .getByText("beta-api")
        .closest('[role="option"]')
        ?.getAttribute("data-selected"),
    ).toBe("true");
  });

  it("hides or disables management during signed-out and auth-refresh states", async () => {
    authUser = null;
    const { rerender } = render(<ControlledPicker open />);
    await screen.findByRole("combobox");
    expect(
      screen.queryByRole("button", { name: "Manage favorites" }),
    ).toBeNull();

    authUser = { id: "alice" };
    authLoading = true;
    rerender(<ControlledPicker open />);
    expect(
      screen
        .getByRole("button", {
          name: "Manage favorites",
        })
        .hasAttribute("disabled"),
    ).toBe(true);
  });

  it("revalidates loading inside the latest star handler", async () => {
    const { rerender } = render(<ControlledPicker open />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Manage favorites" }),
    );
    const alphaStar = await screen.findByRole("button", {
      name: `Favorite ${MODELS[0]!.display_name} (${MODELS[0]!.name})`,
    });

    authLoading = true;
    rerender(<ControlledPicker open />);
    expect(alphaStar.hasAttribute("disabled")).toBe(true);

    const deliveredClick = rs.fn();
    alphaStar.addEventListener("click", deliveredClick);
    alphaStar.removeAttribute("disabled");
    fireEvent.click(alphaStar);

    expect(deliveredClick).toHaveBeenCalledTimes(1);
    expect(setFavorite).not.toHaveBeenCalled();
  });

  it("revalidates a same-reference model catalog while the star stays connected", async () => {
    const mutableModels = [...MODELS];
    render(<ControlledPicker open models={mutableModels} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Manage favorites" }),
    );
    const alphaStar = await screen.findByRole("button", {
      name: `Favorite ${MODELS[0]!.display_name} (${MODELS[0]!.name})`,
    });

    mutableModels.splice(0, 1);
    expect(document.body.contains(alphaStar)).toBe(true);
    fireEvent.click(alphaStar);

    expect(setFavorite).not.toHaveBeenCalled();
  });

  it("announces local and in-memory persistence with a status", async () => {
    const { rerender } = render(<ControlledPicker open />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Manage favorites" }),
    );
    expect(screen.getByRole("status").textContent).toBe(
      "Favorites are stored in this browser.",
    );

    persistence = "memory";
    rerender(<ControlledPicker open />);
    expect(screen.getByRole("status").textContent).toBe(
      "Favorites are stored for this session only.",
    );
  });
});

describe("ModelPickerContent dialog lifecycle", () => {
  it("resets mode, query, and highlight on every closed-to-open edge", async () => {
    const { rerender } = render(
      <ControlledPicker open selectedModelName={MODELS[2]!.name} />,
    );
    fireEvent.change(await screen.findByRole("combobox"), {
      target: { value: "Shared label" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Manage favorites" }));

    rerender(
      <ControlledPicker open={false} selectedModelName={MODELS[2]!.name} />,
    );
    rerender(<ControlledPicker open selectedModelName={MODELS[2]!.name} />);

    const search = await screen.findByRole("combobox");
    expect((search as HTMLInputElement).value).toBe("");
    expect(
      screen
        .getByText("gamma-api")
        .closest('[role="option"]')
        ?.getAttribute("data-selected"),
    ).toBe("true");
  });

  it("lets the owning Dialog close on Escape", async () => {
    render(<StatefulPicker />);
    await screen.findByRole("dialog");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
