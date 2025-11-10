// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import { useTranslations } from "next-intl";

import { cn } from "~/lib/utils";

import { Welcome } from "./welcome";

export function ConversationStarter({
  className,
  onSend,
}: {
  className?: string;
  onSend?: (message: string) => void;
}) {
  const t = useTranslations("chat");
  const questions = t.raw("conversationStarters") as string[];

  return (
    <div
      className={cn(
        "flex h-full flex-col items-center justify-between overflow-auto",
        className,
      )}
    >
      {/* Spacer for flex layout - pushes Welcome to center */}
      <div />
      <div className="pointer-events-none inset-0 flex items-center justify-center">
        <Welcome className="pointer-events-auto mt-14 mb-5 w-[75%]" />
      </div>
      <ul className="mb-6 flex flex-wrap">
        {questions.map((question, index) => (
          <motion.li
            key={`${index}-${question}`}
            className="flex w-1/2 shrink-0 p-2 active:scale-105"
            style={{ transition: "all 0.2s ease-out" }}
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{
              duration: 0.2,
              delay: index * 0.1 + 0.5,
              ease: "easeOut",
            }}
          >
            <div
              className="bg-card text-muted-foreground h-full w-full cursor-pointer rounded-2xl border px-4 py-4 opacity-75 transition-all duration-300 hover:opacity-100 hover:shadow-md"
              onClick={() => {
                onSend?.(question);
              }}
            >
              {question}
            </div>
          </motion.li>
        ))}
      </ul>
    </div>
  );
}
