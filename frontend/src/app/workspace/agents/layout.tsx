import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { isStaticWebsiteOnly } from "@/core/config";

export default function AgentsLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  if (isStaticWebsiteOnly()) {
    redirect("/workspace");
  }

  return children;
}
