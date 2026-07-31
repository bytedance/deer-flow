import { notFound } from "next/navigation";

import ChatPage from "@/app/workspace/chats/[thread_id]/page";
import { DEMO_THREAD_IDS, isDemoThreadId } from "@/core/threads/static-demo";

export const dynamicParams = false;

export function generateStaticParams() {
  return DEMO_THREAD_IDS.map((thread_id) => ({ thread_id }));
}

export default async function PublicShowcasePage({
  params,
}: {
  params: Promise<{ thread_id: string }>;
}) {
  const { thread_id: threadId } = await params;
  if (!isDemoThreadId(threadId)) {
    notFound();
  }
  return <ChatPage />;
}
