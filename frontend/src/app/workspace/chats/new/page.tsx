"use client";

import ChatPage from "../[thread_id]/page";
import { ChatProviders } from "../[thread_id]/providers";

export default function NewChatPage() {
  return (
    <ChatProviders>
      <ChatPage />
    </ChatProviders>
  );
}
