import { redirect } from "next/navigation";

import { DEMO_THREAD_IDS } from "@/core/threads/static-demo";
import { env } from "@/env";

export default function WorkspacePage() {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return redirect(`/workspace/chats/${DEMO_THREAD_IDS[0]}`);
  }
  return redirect("/workspace/chats/new");
}
