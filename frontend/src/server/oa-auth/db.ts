import postgres from "postgres";

import { getOaAuthDatabaseUrl } from "./config";
import { ensureOaAuthSchema } from "./schema";

let sqlSingleton: ReturnType<typeof postgres> | null = null;

export async function getOaAuthSql() {
  const url = getOaAuthDatabaseUrl();
  if (!url) {
    throw new Error("OA auth requires a database URL (OA_AUTH_DATABASE_URL, DEERFLOW_POSTGRES_URL, or DATABASE_URL)");
  }
  sqlSingleton ??= postgres(url, { max: 4 });
  await ensureOaAuthSchema(sqlSingleton);
  return sqlSingleton;
}
