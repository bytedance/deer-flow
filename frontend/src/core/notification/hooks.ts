import { useState, useEffect, useCallback, useRef } from "react";

import { useLocalSettings } from "../settings";

interface NotificationOptions {
  body?: string;
  icon?: string;
  badge?: string;
  tag?: string;
  data?: unknown;
  requireInteraction?: boolean;
  silent?: boolean;
}

interface UseNotificationReturn {
  permission: NotificationPermission;
  isSupported: boolean;
  requestPermission: () => Promise<NotificationPermission>;
  showNotification: (title: string, options?: NotificationOptions) => void;
}

export function useNotification(): UseNotificationReturn {
  const [permission, setPermission] =
    useState<NotificationPermission>("default");
  const [isSupported, setIsSupported] = useState(false);

  const lastNotificationTime = useRef<number | null>(null);

  useEffect(() => {
    // Check if browser supports Notification API
    if ("Notification" in window) {
      setIsSupported(true);
      setPermission(Notification.permission);
    }
  }, []);

  const requestPermission =
    useCallback(async (): Promise<NotificationPermission> => {
      if (!isSupported) {
        console.warn("Notification API is not supported in this browser");
        return "denied";
      }

      const result = await Notification.requestPermission();
      setPermission(result);
      return result;
    }, [isSupported]);

  const [settings] = useLocalSettings();

  const showNotification = useCallback(
    (title: string, options?: NotificationOptions) => {
      if (!isSupported) {
        console.warn("Notification API is not supported");
        return;
      }

      if (!settings.notification.enabled) {
        console.warn("Notification is disabled");
        return;
      }

      const currentPermission = Notification.permission;
      if (currentPermission !== permission) {
        setPermission(currentPermission);
      }

      if (currentPermission !== "granted") {
        console.warn("Notification permission not granted");
        return;
      }

      const now = Date.now();
      if (
        lastNotificationTime.current !== null &&
        now - lastNotificationTime.current < 1000
      ) {
        console.warn("Notification sent too soon");
        return;
      }
      lastNotificationTime.current = now;

      const notification = new Notification(title, options);

      // Optional: Add event listeners
      notification.onclick = () => {
        window.focus();
        notification.close();
      };

      notification.onerror = (error) => {
        console.error("Notification error:", error);
      };
    },
    [isSupported, settings.notification.enabled, permission],
  );

  return {
    permission,
    isSupported,
    requestPermission,
    showNotification,
  };
}
