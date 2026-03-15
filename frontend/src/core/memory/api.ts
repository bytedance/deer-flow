import { apiJson } from "../api/fetch";

import type { UserMemory } from "./types";

export async function loadMemory() {
  return apiJson<UserMemory>("/api/memory");
}
