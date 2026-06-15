import { useCallback, useEffect, useState } from "react";

export function useDocumentVisible(): boolean {
  const [isVisible, setIsVisible] = useState(() => {
    if (typeof document === "undefined") return true;
    return document.visibilityState === "visible";
  });

  const handleVisibilityChange = useCallback(() => {
    setIsVisible(document.visibilityState === "visible");
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    setIsVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [handleVisibilityChange]);

  return isVisible;
}
