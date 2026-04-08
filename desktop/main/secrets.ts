import fs from "node:fs/promises";

import { safeStorage } from "electron";

let secretsPath: string | null = null;

type SecretFile = Record<string, string>;

export function configureSecretsStore(filePath: string) {
  secretsPath = filePath;
}

async function readSecretFile(): Promise<SecretFile> {
  if (secretsPath === null) {
    return {};
  }

  try {
    const raw = await fs.readFile(secretsPath, "utf8");
    return JSON.parse(raw) as SecretFile;
  } catch {
    return {};
  }
}

async function writeSecretFile(secrets: SecretFile) {
  if (secretsPath === null) {
    return;
  }

  await fs.writeFile(secretsPath, JSON.stringify(secrets, null, 2), "utf8");
}

function encodeSecret(value: string) {
  if (!safeStorage.isEncryptionAvailable()) {
    return Buffer.from(value, "utf8").toString("base64");
  }

  return safeStorage.encryptString(value).toString("base64");
}

function decodeSecret(value: string) {
  if (!safeStorage.isEncryptionAvailable()) {
    return Buffer.from(value, "base64").toString("utf8");
  }

  return safeStorage.decryptString(Buffer.from(value, "base64"));
}

export async function getSecretStatuses(providers: string[]) {
  const secrets = await readSecretFile();
  return Object.fromEntries(providers.map((provider) => [provider, Boolean(secrets[provider])])) as Record<string, boolean>;
}

export async function saveSecret(provider: string, value: string) {
  const secrets = await readSecretFile();
  secrets[provider] = encodeSecret(value);
  await writeSecretFile(secrets);
}

export async function deleteSecret(provider: string) {
  const secrets = await readSecretFile();
  delete secrets[provider];
  await writeSecretFile(secrets);
}

export async function getSecret(provider: string) {
  const secrets = await readSecretFile();
  const value = secrets[provider];
  return value ? decodeSecret(value) : null;
}
