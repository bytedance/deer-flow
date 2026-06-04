"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "cookie-consent";

export function CookieConsentBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (localStorage.getItem(STORAGE_KEY) !== "true") {
      setVisible(true);
    }
  }, []);

  if (!visible) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-card px-4 py-3">
      <div className="container-md mx-auto flex items-center justify-between gap-4 text-sm">
        <p className="text-muted-foreground">
          本站使用 Cookie 以改善用户体验。继续使用即表示您同意我们的 Cookie 政策。
        </p>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(STORAGE_KEY, "true");
            setVisible(false);
          }}
          className="bg-primary text-primary-foreground hover:bg-primary/90 shrink-0 rounded-md px-4 py-1.5 text-sm font-medium transition-colors"
        >
          我知道了
        </button>
      </div>
    </div>
  );
}
