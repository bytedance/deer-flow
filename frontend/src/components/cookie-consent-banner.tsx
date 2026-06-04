"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

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
        <Button
          size="sm"
          onClick={() => {
            localStorage.setItem(STORAGE_KEY, "true");
            setVisible(false);
          }}
        >
          我知道了
        </Button>
      </div>
    </div>
  );
}
