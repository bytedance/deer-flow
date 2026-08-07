"use client";

import { ChatProviders } from "@/components/workspace/chats/chat-providers";

export default function AgentChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ChatProviders>{children}</ChatProviders>;
}
