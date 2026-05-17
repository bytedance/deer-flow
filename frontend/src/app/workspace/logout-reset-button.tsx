"use client";

import { useState } from "react";

export function LogoutResetButton() {
  const [isResetting, setIsResetting] = useState(false);

  const handleLogoutReset = async () => {
    setIsResetting(true);
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      window.location.href = "/";
    }
  };

  return (
    <button
      type="button"
      disabled={isResetting}
      onClick={handleLogoutReset}
      className="text-muted-foreground hover:bg-muted rounded-md border px-4 py-2 text-sm disabled:pointer-events-none disabled:opacity-50"
    >
      {isResetting ? "Resetting..." : "Logout & Reset"}
    </button>
  );
}
