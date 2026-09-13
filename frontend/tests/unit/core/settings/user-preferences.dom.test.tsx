import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { useSyncExternalStore } from "react";

import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
} from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  getThreadModelSnapshot,
  resolveThreadContext,
  subscribe,
  updateLocalSettings,
} from "@/core/settings/store";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";

const mocks = rs.hoisted(() => ({
  user: { id: "alice" },
  fetch: rs.fn(),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user }),
}));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));

function Consumer() {
  const settings = useSyncExternalStore(
    subscribe,
    getBaseSettingsSnapshot,
    () => DEFAULT_LOCAL_SETTINGS,
  );
  return (
    <output>{`${settings.notification.enabled}:${settings.context.model_name ?? "default"}:${settings.context.mode ?? "default"}`}</output>
  );
}
function Workspace() {
  return (
    <UserPreferencesBoundary>
      <Consumer />
    </UserPreferencesBoundary>
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  mocks.user = { id: "alice" };
  mocks.fetch.mockReset();
});
afterEach(() => {
  cleanup();
});

describe("authenticated workspace preferences", () => {
  it("does not upload automatic model fallback or mask a later server model", async () => {
    let finish!: (response: Response) => void;
    mocks.fetch.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
    render(<Workspace />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    act(() =>
      resolveThreadContext("slow-hydration", {
        model_name: "fallback",
        mode: "pro",
      }),
    );
    expect(
      sessionStorage.getItem("deerflow.preferences.alice.pending"),
    ).toBeNull();
    expect(getThreadModelSnapshot("slow-hydration")).toBeUndefined();
    finish(Response.json({ model_name: "server-choice", mode: "ultra" }));
    await screen.findByText("true:server-choice:ultra");
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
  });
  it("restores server preferences after clearing browser storage and sends only edited fields", async () => {
    let server = {
      notification_enabled: false,
      model_name: "saved-model",
      mode: "pro",
    };
    mocks.fetch.mockImplementation(async (_url: string, init: RequestInit) => {
      expect(new Headers(init.headers).get("X-Expected-User-Id")).toBe("alice");
      if (init.method === "PATCH") {
        expect(JSON.parse(init.body as string)).toEqual({
          notification_enabled: true,
        });
        server = { ...server, ...JSON.parse(init.body as string) };
        return new Response(null, { status: 204 });
      }
      return Response.json(server);
    });
    const view = render(<Workspace />);
    await screen.findByText("false:saved-model:pro");
    act(() => updateLocalSettings("notification", { enabled: true }));
    await waitFor(() => expect(server.notification_enabled).toBe(true));
    await waitFor(() =>
      expect(sessionStorage.getItem("deerflow.preferences.alice.pending")).toBe(
        "{}",
      ),
    );
    view.unmount();
    localStorage.clear();
    render(<Workspace />);
    await screen.findByText("true:saved-model:pro");
  });

  it("does not import legacy preferences or expose the previous account on a switch", async () => {
    localStorage.setItem(
      LOCAL_SETTINGS_KEY,
      JSON.stringify({
        notification: { enabled: false },
        context: { model_name: "legacy-secret" },
      }),
    );
    mocks.fetch.mockImplementation(async (_url: string, init: RequestInit) => {
      expect(init.method).toBe("GET");
      const owner = new Headers(init.headers).get("X-Expected-User-Id");
      return Response.json(
        owner === "alice" ? { model_name: "alice-model" } : {},
      );
    });
    const view = render(<Workspace />);
    await screen.findByText("true:alice-model:default");
    mocks.user = { id: "bob" };
    view.rerender(<Workspace />);
    expect(screen.queryByText("true:alice-model:default")).toBeNull();
    await screen.findByText("true:default:default");
    expect(localStorage.getItem(LOCAL_SETTINGS_KEY)).toContain("legacy-secret");
  });

  it("retries failed initialization on reconnect and retains pending changes across reload", async () => {
    mocks.fetch.mockRejectedValue(new Error("offline"));
    const view = render(<Workspace />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    act(() => updateLocalSettings("context", { mode: "ultra" }));
    expect(
      JSON.parse(sessionStorage.getItem("deerflow.preferences.alice.pending")!),
    ).toEqual({ mode: "ultra" });
    view.unmount();
    mocks.fetch.mockImplementation(async (_url: string, init: RequestInit) => {
      if (init.method === "PATCH") {
        expect(JSON.parse(init.body as string)).toEqual({ mode: "ultra" });
        return new Response(null, { status: 204 });
      }
      return Response.json({ model_name: "remote" });
    });
    render(<Workspace />);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await screen.findByText("true:remote:ultra");
    await waitFor(() =>
      expect(sessionStorage.getItem("deerflow.preferences.alice.pending")).toBe(
        "{}",
      ),
    );
  });

  it("does not write an unchanged cache back in response to a storage event", async () => {
    mocks.fetch.mockResolvedValue(Response.json({ mode: "pro" }));
    // Each HTTP request needs its own readable Response body.
    mocks.fetch.mockImplementation(async () => Response.json({ mode: "pro" }));
    render(<Workspace />);
    await screen.findByText("true:default:pro");
    const writes = rs.spyOn(Storage.prototype, "setItem");
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "deerflow.preferences.alice" }),
      );
    });
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(2));
    expect(writes).not.toHaveBeenCalled();
    writes.mockRestore();
  });

  it("stops requests when another tab changes the authenticated account", async () => {
    sessionStorage.setItem(
      "deerflow.preferences.alice.pending",
      JSON.stringify({ mode: "ultra" }),
    );
    mocks.fetch.mockImplementation(
      async () => new Response(null, { status: 409 }),
    );
    render(<Workspace />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    await act(async () => {
      await Promise.resolve();
    });
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    expect(
      sessionStorage.getItem("deerflow.preferences.alice.pending"),
    ).toContain("ultra");
  });
});
