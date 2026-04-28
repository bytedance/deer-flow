import { env } from "@/env";

export interface DirectoryEntry {
  name: string;
  path: string;
  isDirectory: boolean;
}

export interface FileContent {
  path: string;
  name: string;
  content: string;
  size: number;
  modifiedAt: string;
}

const getBaseUrl = () => {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  return "";
};

export async function browseDirectory(
  threadId: string,
  path = "/mnt/user-data/workspace",
  extensions: string[] = ["md", "txt", "json", "log"],
): Promise<DirectoryEntry[]> {
  const url = `${getBaseUrl()}/api/threads/${threadId}/filesystem/browse`;
  const params = new URLSearchParams({
    path,
    extensions: extensions.join(","),
  });

  console.log(" Browsing directory:", `${url}?${params}`);

  const response = await fetch(`${url}?${params}`);

  console.log(" Response status:", response.status);

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to browse directory" }));
    console.error(" Browse directory error:", error);
    throw new Error(error.detail ?? "Failed to browse directory");
  }

  const data = await response.json();
  console.log("📁 Directory entries:", data.entries?.length ?? 0, "entries");
  return data.entries ?? [];
}

export async function readFile(
  threadId: string,
  path: string,
): Promise<FileContent> {
  const url = `${getBaseUrl()}/api/threads/${threadId}/filesystem/read`;
  const params = new URLSearchParams({ path });

  const response = await fetch(`${url}?${params}`);

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to read file" }));
    throw new Error(error.detail ?? "Failed to read file");
  }

  return response.json();
}

export async function writeFile(
  threadId: string,
  path: string,
  content: string,
): Promise<void> {
  const url = `${getBaseUrl()}/api/threads/${threadId}/filesystem/write`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path, content }),
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to write file" }));
    throw new Error(error.detail ?? "Failed to write file");
  }
}

export async function deleteFile(
  threadId: string,
  path: string,
): Promise<void> {
  const url = `${getBaseUrl()}/api/threads/${threadId}/filesystem/delete`;
  const params = new URLSearchParams({ path });

  const response = await fetch(`${url}?${params}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to delete file" }));
    throw new Error(error.detail ?? "Failed to delete file");
  }
}
