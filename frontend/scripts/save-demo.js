import { config } from "dotenv";
import fs from "fs";
import path from "path";
import { env } from "process";

export async function main() {
  const url = new URL(process.argv[2]);
  const threadId = url.pathname.split("/").pop();
  const host = url.host;
  const apiURL = new URL(
    `/api/langgraph/threads/${threadId}/history`,
    `${url.protocol}//${host}`,
  );
  const response = await fetch(apiURL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      limit: 10,
    }),
  });

  const data = (await response.json())[0];
  if (!data) {
    console.error("No data found");
    return;
  }

  const title = data.values.title;

  const rootPath = path.resolve(process.cwd(), "public/demo/threads", threadId);
  if (fs.existsSync(rootPath)) {
    fs.rmSync(rootPath, { recursive: true });
  }
  fs.mkdirSync(rootPath, { recursive: true });
  fs.writeFileSync(
    path.resolve(rootPath, "thread.json"),
    JSON.stringify(data, null, 2),
  );
  const backendRootPath = path.resolve(
    process.cwd(),
    "../backend/.deer-flow/threads",
    threadId,
  );
  copyFolder("user-data/outputs", rootPath, backendRootPath);
  copyFolder("user-data/uploads", rootPath, backendRootPath);
  console.info(`Saved demo "${title}" to ${rootPath}`);
}

function copyFolder(relPath, rootPath, backendRootPath) {
  const outputsPath = path.resolve(backendRootPath, relPath);
  if (fs.existsSync(outputsPath)) {
    fs.cpSync(outputsPath, path.resolve(rootPath, relPath), {
      recursive: true,
    });
  }
}

config();
main();
