// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import { Brain, Search, Code, FileText, Compass, Database } from "lucide-react";
import { useTranslations } from "next-intl";

import { LoadingAnimation } from "~/components/deer-flow/loading-animation";
import { Card, CardContent } from "~/components/ui/card";
import { useStore } from "~/core/store";
import { cn } from "~/lib/utils";

const AGENT_CONFIG = {
  coordinator: {
    icon: Compass,
    nameKey: "coordinator",
    colorClass: "text-blue-600",
    bgClass: "bg-blue-50 border-blue-200",
  },
  background_investigator: {
    icon: Database,
    nameKey: "backgroundInvestigator",
    colorClass: "text-purple-600",
    bgClass: "bg-purple-50 border-purple-200",
  },
  planner: {
    icon: Brain,
    nameKey: "planner",
    colorClass: "text-green-600",
    bgClass: "bg-green-50 border-green-200",
  },
  researcher: {
    icon: Search,
    nameKey: "researcher",
    colorClass: "text-orange-600",
    bgClass: "bg-orange-50 border-orange-200",
  },
  coder: {
    icon: Code,
    nameKey: "coder",
    colorClass: "text-indigo-600",
    bgClass: "bg-indigo-50 border-indigo-200",
  },
  reporter: {
    icon: FileText,
    nameKey: "reporter",
    colorClass: "text-red-600",
    bgClass: "bg-red-50 border-red-200",
  },
} as const;

export function AgentStatus({ className }: { className?: string }) {
  const t = useTranslations("chat.agents");
  const currentAgent = useStore((state) => state.currentAgent);
  const responding = useStore((state) => state.responding);
  const ongoingResearchId = useStore((state) => state.ongoingResearchId);
  const researchPlanIds = useStore((state) => state.researchPlanIds);
  const messages = useStore((state) => state.messages);

  if (!responding || !currentAgent) {
    return null;
  }

  // Get config with fallback for unknown agents
  const config = AGENT_CONFIG[currentAgent as keyof typeof AGENT_CONFIG] || {
    icon: Brain,
    nameKey: "unknown",
    colorClass: "text-gray-600",
    bgClass: "bg-gray-50 border-gray-200",
  };

  // Calculate progress information
  const progressInfo = (() => {
    if (!ongoingResearchId) {
      return null;
    }

    const planId = researchPlanIds.get(ongoingResearchId);
    if (!planId) {
      return null;
    }

    const planMessage = messages.get(planId);
    if (!planMessage?.content) {
      return null;
    }

    try {
      const plan = JSON.parse(planMessage.content);
      if (!plan.steps || !Array.isArray(plan.steps)) {
        return null;
      }

      const totalSteps = plan.steps.length;
      const completedSteps = plan.steps.filter((step: any) => step.execution_res).length;
      const currentStep = completedSteps + 1;

      // Only show progress for research/coder agents (actual execution steps)
      if (currentAgent === "researcher" || currentAgent === "coder") {
        return {
          current: Math.min(currentStep, totalSteps),
          total: totalSteps,
        };
      }
    } catch (e) {
      // Ignore JSON parse errors
    }

    return null;
  })();

  const Icon = config.icon;

  return (
    <motion.div
      className={cn("fixed top-16 right-4 z-50", className)}
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.3 }}
    >
      <Card className={cn("shadow-lg", config.bgClass)}>
        <CardContent className="flex items-center gap-3 p-3">
          <div className={cn("flex items-center justify-center", config.colorClass)}>
            <Icon size={18} />
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-medium text-gray-900">
              {t(config.nameKey)}
            </span>
            <span className="text-xs text-gray-600">{t("working")}</span>
          </div>
          <LoadingAnimation className="scale-75" />
        </CardContent>
      </Card>
    </motion.div>
  );
}