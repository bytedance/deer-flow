"use client";

import { useEffect } from "react";

import { startEhmHostBridge } from "@/core/auth/ehm-host-bridge";

export function EhmHostBridgeProvider() {
  useEffect(() => {
    return startEhmHostBridge();
  }, []);

  return null;
}
