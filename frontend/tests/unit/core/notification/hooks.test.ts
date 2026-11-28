import { afterEach, describe, expect, test, rs } from "@rstest/core";

type NotificationInstance = {
  onclick: (() => void) | null;
  onerror: ((error: Event) => void) | null;
  close: () => void;
};

// Chrome for Android's message for `new Notification()`.
const ANDROID_CONSTRUCTOR_ERROR =
  "Failed to construct 'Notification': Illegal constructor. Use ServiceWorkerRegistration.showNotification() instead.";

async function loadNotificationHook({
  browserPermission = "granted",
  hookPermission = "granted",
  failingConstructions = 0,
}: {
  browserPermission?: NotificationPermission;
  hookPermission?: NotificationPermission;
  /** How many constructions throw before one succeeds. */
  failingConstructions?: number;
} = {}) {
  let remainingFailures = failingConstructions;
  const notifications: Array<{
    title: string;
    options: NotificationOptions | undefined;
    instance: NotificationInstance;
  }> = [];

  class MockNotification implements NotificationInstance {
    static permission: NotificationPermission = browserPermission;
    static requestPermission = rs.fn(async () => {
      MockNotification.permission = "granted";
      return "granted" as const;
    });

    onclick: (() => void) | null = null;
    onerror: ((error: Event) => void) | null = null;
    close = rs.fn();

    constructor(title: string, options?: NotificationOptions) {
      if (remainingFailures > 0) {
        remainingFailures -= 1;
        throw new TypeError(ANDROID_CONSTRUCTOR_ERROR);
      }
      notifications.push({ title, options, instance: this });
    }
  }

  rs.resetModules();
  rs.doMock("react", () => ({
    useCallback: <T extends (...args: never[]) => unknown>(callback: T) =>
      callback,
    useEffect: () => undefined,
    useRef: <T>(initialValue: T) => ({ current: initialValue }),
    useState: <T>(initialValue: T) => {
      if (initialValue === "default") {
        return [hookPermission, rs.fn()] as const;
      }
      if (initialValue === false) {
        return [true, rs.fn()] as const;
      }
      return [initialValue, rs.fn()] as const;
    },
  }));
  rs.doMock("@/core/settings", () => ({
    useLocalSettings: () => [
      {
        notification: { enabled: true },
        tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
        context: {
          model_name: undefined,
          mode: undefined,
          reasoning_effort: undefined,
        },
      },
      rs.fn(),
    ],
  }));
  rs.stubGlobal("window", { focus: rs.fn() });
  rs.stubGlobal("Notification", MockNotification);

  const { useNotification } = await import("@/core/notification/hooks");

  return {
    notifications,
    useNotification,
  };
}

afterEach(() => {
  rs.restoreAllMocks();
  rs.doUnmock("react");
  rs.doUnmock("@/core/settings");
  rs.unstubAllGlobals();
  rs.resetModules();
});

describe("useNotification", () => {
  test("allows the first notification immediately after the hook is created", async () => {
    const { notifications, useNotification } = await loadNotificationHook();
    const { showNotification } = useNotification();

    showNotification("Finished", { body: "Conversation finished" });

    expect(notifications).toHaveLength(1);
    expect(notifications[0]?.title).toBe("Finished");
    expect(notifications[0]?.options?.body).toBe("Conversation finished");
  });

  test("rate limits only after a notification has been sent", async () => {
    const { notifications, useNotification } = await loadNotificationHook();
    const { showNotification } = useNotification();

    showNotification("First");
    showNotification("Second");

    expect(notifications.map((notification) => notification.title)).toEqual([
      "First",
    ]);
  });

  test("keeps a constructor failure inside the hook", async () => {
    const { notifications, useNotification } = await loadNotificationHook({
      failingConstructions: 1,
    });
    const warn = rs.spyOn(console, "warn").mockImplementation(() => undefined);
    const { showNotification } = useNotification();

    expect(() => showNotification("Finished")).not.toThrow();

    expect(notifications).toHaveLength(0);
    expect(warn).toHaveBeenCalledWith(
      "Notification could not be created:",
      expect.objectContaining({ message: ANDROID_CONSTRUCTOR_ERROR }),
    );
  });

  test("does not start the rate limit with a notification that was not created", async () => {
    const { notifications, useNotification } = await loadNotificationHook({
      failingConstructions: 1,
    });
    rs.spyOn(console, "warn").mockImplementation(() => undefined);
    const { showNotification } = useNotification();

    showNotification("Failed");
    showNotification("Created");
    showNotification("Too soon");

    expect(notifications.map((notification) => notification.title)).toEqual([
      "Created",
    ]);
  });

  test("uses the browser's current permission when another hook requested it", async () => {
    const { notifications, useNotification } = await loadNotificationHook({
      browserPermission: "granted",
      hookPermission: "default",
    });
    const { showNotification } = useNotification();

    showNotification("Finished elsewhere");

    expect(notifications.map((notification) => notification.title)).toEqual([
      "Finished elsewhere",
    ]);
  });
});
