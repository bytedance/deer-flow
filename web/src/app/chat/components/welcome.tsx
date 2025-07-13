// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import { useTranslations } from "next-intl";

import { cn } from "~/lib/utils";

export function Welcome({ className }: { className?: string }) {
  const t = useTranslations("chat.welcome");

  return (
    <motion.div
      className={cn("flex flex-col", className)}
      style={{ transition: "all 0.2s ease-out" }}
      initial={{ opacity: 0, scale: 0.85 }}
      animate={{ opacity: 1, scale: 1 }}
    >
      <h3 className="mb-2 text-center text-3xl font-medium">{t("greeting")}</h3>
      <div className="text-muted-foreground px-4 text-center text-lg">
        {t("description")}
      </div>
    </motion.div>
  );
}
