import { isStaticWebsiteOnly } from "@/core/static-mode";
import { DEMO_THREAD_IDS } from "@/core/threads/static-demo";

import { ChatProviders } from "./providers";

export function generateStaticParams() {
  if (!isStaticWebsiteOnly()) {
    return [];
  }
  return DEMO_THREAD_IDS.map((thread_id) => ({ thread_id }));
}

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ChatProviders>{children}</ChatProviders>;
}
