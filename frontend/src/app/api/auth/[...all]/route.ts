import { toNextJsHandler } from "better-auth/next-js";

import { auth } from "@/server/better-auth";

export const { GET, POST } = toNextJsHandler(auth.handler);
