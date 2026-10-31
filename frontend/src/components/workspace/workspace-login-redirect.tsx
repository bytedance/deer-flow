"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { buildLoginUrl, currentReturnPath } from "@/core/auth/types";

/**
 * Sends a signed-out visitor to the login page with this page as `next`.
 *
 * The workspace layout learns the session is missing on the server, but a
 * layout cannot read the request URL, so a server redirect there would drop
 * the page the user opened (e.g. a `?task_id=` link from a notification).
 * The browser still has it. `replace` keeps this empty page out of history,
 * as the server redirect did.
 */
export function WorkspaceLoginRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace(buildLoginUrl(currentReturnPath()));
  }, [router]);

  return null;
}
