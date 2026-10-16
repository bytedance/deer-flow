import { headers } from "next/headers";

import {
  REQUEST_ROUTE_HEADER,
  authenticatedEntryReturnPath,
  workspaceLoginHref,
} from "./return-path";

export async function getWorkspaceLoginHref() {
  return workspaceLoginHref((await headers()).get(REQUEST_ROUTE_HEADER));
}

export async function getAuthenticatedEntryReturnPath() {
  return authenticatedEntryReturnPath(
    (await headers()).get(REQUEST_ROUTE_HEADER),
  );
}
