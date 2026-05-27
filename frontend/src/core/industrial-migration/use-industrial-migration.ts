"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useTenant } from "@/core/tenant/hooks";

import {
  acceptMigration,
  declineMigration,
  getMigrationStatus,
  markMigrationPrompted,
} from "./api";

type MigrationPhase =
  | "checking"
  | "prompting"
  | "accepting"
  | "declining"
  | "completed"
  | "skipped"
  | "error";

export function useIndustrialMigration() {
  const [tenantId] = useTenant();
  const [phase, setPhase] = useState<MigrationPhase>("checking");
  const [showDialog, setShowDialog] = useState(false);
  const [enabledCount, setEnabledCount] = useState(0);
  const checkedRef = useRef(false);

  useEffect(() => {
    if (checkedRef.current || !tenantId) return;
    checkedRef.current = true;

    let cancelled = false;

    void (async () => {
      try {
        const status = await getMigrationStatus(tenantId);
        if (cancelled) return;

        if (status.completed) {
          setPhase("completed");
          return;
        }

        if (!status.prompted) {
          await markMigrationPrompted(tenantId);
          if (cancelled) return;
        }

        setPhase("prompting");
        setShowDialog(true);
      } catch {
        if (!cancelled) {
          setPhase("completed");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const handleAccept = useCallback(async () => {
    setPhase("accepting");
    try {
      const result = await acceptMigration(tenantId);
      setEnabledCount(result.enabled_count);
      setShowDialog(false);
      setPhase("completed");
      toast.success(
        result.enabled_count > 0
          ? `已启用 ${result.enabled_count} 个工业智能技能`
          : "Industrial skills are already enabled",
      );
    } catch (err) {
      setPhase("error");
      toast.error((err as Error).message);
    }
  }, [tenantId]);

  const handleDecline = useCallback(async () => {
    setPhase("declining");
    try {
      await declineMigration(tenantId);
      setShowDialog(false);
      setPhase("skipped");
    } catch (err) {
      setPhase("error");
      toast.error((err as Error).message);
    }
  }, [tenantId]);

  return {
    phase,
    showDialog,
    enabledCount,
    isProcessing: phase === "accepting" || phase === "declining",
    onAccept: handleAccept,
    onDecline: handleDecline,
  };
}
