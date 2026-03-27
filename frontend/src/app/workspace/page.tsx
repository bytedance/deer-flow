import fs from "fs";
import path from "path";

import { redirect } from "next/navigation";

import { isStaticWebsiteOnly } from "@/core/config";

export default function WorkspacePage() {
  if (isStaticWebsiteOnly()) {
    const firstThread = fs
      .readdirSync(path.resolve(process.cwd(), "public/demo/threads"), {
        withFileTypes: true,
      })
      .find((thread) => thread.isDirectory() && !thread.name.startsWith("."));
    if (firstThread) {
      return redirect(`/workspace/chats/${firstThread.name}`);
    }
  }
  return redirect("/workspace/chats/new");
}
