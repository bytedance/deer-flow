// resolveServiceURL.ts

import { z } from "zod";

// 定义配置文件 Schema
export const ConfigSchema = z.object({
  API_URL: z.string().url(),
});

export type AppConfig = z.infer<typeof ConfigSchema>;

// 改为异步函数，从 /config.json 加载配置
export async function resolveServiceURL(path: string): Promise<string> {
  let BASE_URL: string;

  try {
    const res = await fetch("/config.json");
    if (!res.ok) throw new Error("Failed to load config.json");

    const config = ConfigSchema.parse(await res.json());
    BASE_URL = config.API_URL;
  } catch (error) {
    console.warn("Config load failed. Falling back to build-time env.");
    BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/";
  }

  // 确保 URL 以 / 结尾
  if (!BASE_URL.endsWith("/")) {
    BASE_URL += "/";
  }

  return new URL(path, BASE_URL).toString();
}