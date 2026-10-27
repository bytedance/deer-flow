import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { NotificationSettingsPage } from "@/components/workspace/settings/notification-settings-page";
import { fetch as fetcher } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { enUS } from "@/core/i18n/locales/en-US";
import { useNotification } from "@/core/notification/hooks";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));
rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: rs.fn() }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/notification/hooks", () => ({ useNotification: rs.fn() }));
rs.mock("@/core/settings", () => ({
  useLocalSettings: () => [{ notification: { enabled: true } }, rs.fn()],
}));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));

const defaults = { feishu: true, wecom: true, wechat: true, qq: true };
const provider = (id: string, connected = true, supported = true) => ({
  provider: id,
  display_name: id,
  connection_status: connected ? "connected" : "not_connected",
  proactive_notifications: supported,
  enabled: true,
  configured: true,
  auth_mode: "connect_code",
  credential_fields: [],
});
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function viewer(id: string) {
  rs.mocked(useAuth).mockReturnValue({
    user: { id },
    isLoading: false,
  } as ReturnType<typeof useAuth>);
}
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const element = () => (
    <QueryClientProvider client={client}>
      <NotificationSettingsPage />
    </QueryClientProvider>
  );
  const result = render(element());
  return { ...result, refresh: () => result.rerender(element()), client };
}
beforeEach(() => {
  viewer("alice");
  rs.mocked(useNotification).mockReturnValue({
    isSupported: false,
    permission: "default",
    requestPermission: rs.fn(),
    showNotification: rs.fn(),
  });
  rs.mocked(fetcher).mockImplementation(async (url) =>
    (typeof url === "string" ? url : url.url).endsWith("/providers")
      ? json({
          enabled: true,
          providers: [
            provider("feishu"),
            provider("wecom"),
            provider("wechat"),
            provider("qq"),
            provider("slack", true, false),
          ],
        })
      : json(defaults),
  );
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

test("offers connected push-capable apps even when browser notifications are unsupported", async () => {
  mount();
  for (const name of ["Feishu / Lark", "WeCom", "WeChat", "QQ"]) {
    const toggle = await screen.findByRole("switch", {
      name: `${name} scheduled task notifications`,
    });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  }
  expect(screen.queryByRole("switch", { name: /Slack/ })).toBeNull();
  expect(
    screen.getByText("Your browser does not support notifications."),
  ).toBeTruthy();
  expect(screen.getByText(/does not affect chatting/)).toBeTruthy();
});

test("saves only the changed provider with the current viewer and waits for acknowledgement", async () => {
  const saved = deferred<Response>();
  const original = rs.mocked(fetcher).getMockImplementation()!;
  rs.mocked(fetcher).mockImplementation((url, init) =>
    init?.method === "PATCH" ? saved.promise : original(url, init),
  );
  mount();
  const toggle = await screen.findByRole("switch", {
    name: "Feishu / Lark scheduled task notifications",
  });
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(
      rs
        .mocked(fetcher)
        .mock.calls.some(([, init]) => init?.method === "PATCH"),
    ).toBe(true),
  );
  const [, request] = rs
    .mocked(fetcher)
    .mock.calls.find(([, init]) => init?.method === "PATCH")!;
  expect(JSON.parse(request!.body as string)).toEqual({ feishu: false });
  expect(new Headers(request?.headers).get("X-Expected-User-Id")).toBe("alice");
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  expect(toggle.hasAttribute("disabled")).toBe(true);
  await act(async () => saved.resolve(json({ ...defaults, feishu: false })));
  await waitFor(() =>
    expect(toggle.getAttribute("aria-checked")).toBe("false"),
  );
});

test("a failed save leaves the confirmed switch unchanged and can be retried", async () => {
  const original = rs.mocked(fetcher).getMockImplementation()!;
  rs.mocked(fetcher).mockImplementation((url, init) =>
    init?.method === "PATCH"
      ? Promise.resolve(json({}, 503))
      : original(url, init),
  );
  mount();
  const toggle = await screen.findByRole("switch", {
    name: "WeCom scheduled task notifications",
  });
  fireEvent.click(toggle);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  expect(toggle.hasAttribute("disabled")).toBe(false);
});

test("pending preferences never expose default-on switches", async () => {
  const pending = deferred<Response>();
  const original = rs.mocked(fetcher).getMockImplementation()!;
  rs.mocked(fetcher).mockImplementation((url, init) =>
    (typeof url === "string" ? url : url.url).endsWith(
      "/notification-preferences",
    )
      ? pending.promise
      : original(url, init),
  );
  mount();
  expect(await screen.findByRole("status")).toBeTruthy();
  expect(screen.queryByRole("switch")).toBeNull();
  await act(async () => pending.resolve(json({ ...defaults, feishu: false })));
  expect(
    (
      await screen.findByRole("switch", {
        name: "Feishu / Lark scheduled task notifications",
      })
    ).getAttribute("aria-checked"),
  ).toBe("false");
});

test.each([404, 405])(
  "old backend %s shows unavailable without a local switch",
  async (status) => {
    const original = rs.mocked(fetcher).getMockImplementation()!;
    rs.mocked(fetcher).mockImplementation((url, init) =>
      (typeof url === "string" ? url : url.url).endsWith(
        "/notification-preferences",
      )
        ? Promise.resolve(json({}, status))
        : original(url, init),
    );
    mount();
    expect(
      await screen.findByText(/does not support notification preferences/),
    ).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(
      rs
        .mocked(fetcher)
        .mock.calls.every(([, init]) => init?.method !== "PATCH"),
    ).toBe(true);
  },
);

test("disconnected and unsupported apps are omitted", async () => {
  const original = rs.mocked(fetcher).getMockImplementation()!;
  rs.mocked(fetcher).mockImplementation((url, init) =>
    (typeof url === "string" ? url : url.url).endsWith("/providers")
      ? Promise.resolve(
          json({
            enabled: true,
            providers: [provider("feishu", false), provider("qq", true, false)],
          }),
        )
      : original(url, init),
  );
  mount();
  expect(await screen.findByText(/Connect an app that supports/)).toBeTruthy();
  expect(screen.queryByRole("switch")).toBeNull();
});

test("switching viewers hides old values and ignores a late save", async () => {
  const saved = deferred<Response>();
  const original = rs.mocked(fetcher).getMockImplementation()!;
  rs.mocked(fetcher).mockImplementation((url, init) => {
    if (init?.method === "PATCH") return saved.promise;
    if (
      (typeof url === "string" ? url : url.url).endsWith(
        "/notification-preferences",
      ) &&
      new Headers(init?.headers).get("X-Expected-User-Id") === "bob"
    )
      return Promise.resolve(json({ ...defaults, feishu: false }));
    return original(url, init);
  });
  const view = mount();
  fireEvent.click(
    await screen.findByRole("switch", {
      name: "Feishu / Lark scheduled task notifications",
    }),
  );
  viewer("bob");
  view.refresh();
  await waitFor(() =>
    expect(
      screen
        .getByRole("switch", {
          name: "Feishu / Lark scheduled task notifications",
        })
        .getAttribute("aria-checked"),
    ).toBe("false"),
  );
  await act(async () => saved.resolve(json(defaults)));
  expect(
    screen
      .getByRole("switch", {
        name: "Feishu / Lark scheduled task notifications",
      })
      .getAttribute("aria-checked"),
  ).toBe("false");
});

test("a failed load exposes retry and no switches until fresh values arrive", async () => {
  let failed = true;
  const original = rs.mocked(fetcher).getMockImplementation()!;
  rs.mocked(fetcher).mockImplementation((url, init) =>
    (typeof url === "string" ? url : url.url).endsWith(
      "/notification-preferences",
    ) && failed
      ? Promise.resolve(json({}, 503))
      : original(url, init),
  );
  mount();
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByRole("switch")).toBeNull();
  failed = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(
    await screen.findByRole("switch", {
      name: "QQ scheduled task notifications",
    }),
  ).toBeTruthy();
});

test("auth-disabled local user can save with the default viewer identity", async () => {
  viewer("default");
  mount();
  fireEvent.click(
    await screen.findByRole("switch", {
      name: "QQ scheduled task notifications",
    }),
  );
  await waitFor(() =>
    expect(
      rs
        .mocked(fetcher)
        .mock.calls.some(([, init]) => init?.method === "PATCH"),
    ).toBe(true),
  );
  const [, request] = rs
    .mocked(fetcher)
    .mock.calls.find(([, init]) => init?.method === "PATCH")!;
  expect(new Headers(request?.headers).get("X-Expected-User-Id")).toBe(
    "default",
  );
});

test("a late preference load cannot replace the next viewer's settings", async () => {
  const previous = deferred<Response>();
  const original = rs.mocked(fetcher).getMockImplementation()!;
  rs.mocked(fetcher).mockImplementation((url, init) =>
    (typeof url === "string" ? url : url.url).endsWith(
      "/notification-preferences",
    ) && new Headers(init?.headers).get("X-Expected-User-Id") === "alice"
      ? previous.promise
      : original(url, init),
  );
  const view = mount();
  viewer("bob");
  view.refresh();
  expect(
    (
      await screen.findByRole("switch", {
        name: "QQ scheduled task notifications",
      })
    ).getAttribute("aria-checked"),
  ).toBe("true");
  await act(async () => previous.resolve(json({ ...defaults, qq: false })));
  expect(
    screen
      .getByRole("switch", { name: "QQ scheduled task notifications" })
      .getAttribute("aria-checked"),
  ).toBe("true");
});

test("renders default-off task & goal event switches and saves an event toggle", async () => {
  const original = rs.mocked(fetcher).getMockImplementation()!;
  rs.mocked(fetcher).mockImplementation((url, init) =>
    init?.method === "PATCH"
      ? Promise.resolve(
          json({
            ...defaults,
            run_completed: false,
            run_failed: false,
            human_input_requested: true,
          }),
        )
      : original(url, init),
  );
  mount();
  for (const label of [
    "Task or goal completed notifications",
    "Task or goal failed notifications",
    "Needs your input notifications",
  ]) {
    const toggle = await screen.findByRole("switch", { name: label });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
  }
  const inputToggle = screen.getByRole("switch", {
    name: "Needs your input notifications",
  });
  fireEvent.click(inputToggle);
  await waitFor(() =>
    expect(inputToggle.getAttribute("aria-checked")).toBe("true"),
  );
  const [, request] = rs
    .mocked(fetcher)
    .mock.calls.find(([, init]) => init?.method === "PATCH")!;
  expect(JSON.parse(request!.body as string)).toEqual({
    human_input_requested: true,
  });
});
