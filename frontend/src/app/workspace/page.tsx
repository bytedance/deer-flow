import { redirect } from "next/navigation";

import { DEMO_THREAD_IDS } from "@/core/threads/static-demo";
import { env } from "@/env";

export default async function WorkspacePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (Array.isArray(value))
      for (const item of value) params.append(key, item);
    else if (value !== undefined) params.append(key, value);
  }
  const target =
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
      ? `/workspace/chats/${DEMO_THREAD_IDS[0]}`
      : "/workspace/chats/new";
  return redirect(target + (params.size ? "?" + params.toString() : ""));
}
