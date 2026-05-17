"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

export function LogoutResetButton() {
  const [isResetting, setIsResetting] = useState(false);

  const handleLogoutReset = async () => {
    if (isResetting) return;

    setIsResetting(true);
    try {
      const response = await fetch("/logout-reset", {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) {
        console.error("Logout reset request failed:", response.status);
      }
    } catch (err) {
      console.error("Logout reset request failed:", err);
    } finally {
      window.location.href = "/";
    }
  };

  return (
    <Button
      type="button"
      variant="outline"
      disabled={isResetting}
      onClick={handleLogoutReset}
      className="text-muted-foreground min-w-32"
    >
      {isResetting ? "Resetting..." : "Logout & Reset"}
    </Button>
  );
}
