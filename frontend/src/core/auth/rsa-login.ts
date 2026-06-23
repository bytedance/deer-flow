function base64ToBytes(value: string): Uint8Array {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return window.btoa(binary);
}

function base64UrlToBytes(value: string): Uint8Array {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  return base64ToBytes(padded);
}

function bytesToBigInt(bytes: Uint8Array): bigint {
  let result = 0n;
  for (const byte of bytes) {
    result = (result << 8n) + BigInt(byte);
  }
  return result;
}

function bigIntToFixedBytes(value: bigint, length: number): Uint8Array {
  const bytes = new Uint8Array(length);
  let remaining = value;
  for (let i = length - 1; i >= 0; i -= 1) {
    bytes[i] = Number(remaining & 0xffn);
    remaining >>= 8n;
  }
  return bytes;
}

function modPow(base: bigint, exponent: bigint, modulus: bigint): bigint {
  if (modulus === 1n) {
    return 0n;
  }

  let result = 1n;
  let currentBase = base % modulus;
  let currentExponent = exponent;

  while (currentExponent > 0n) {
    if (currentExponent % 2n === 1n) {
      result = (result * currentBase) % modulus;
    }
    currentExponent >>= 1n;
    currentBase = (currentBase * currentBase) % modulus;
  }

  return result;
}

function pemToDer(publicKeyPem: string): Uint8Array {
  const body = publicKeyPem
    .replace("-----BEGIN PUBLIC KEY-----", "")
    .replace("-----END PUBLIC KEY-----", "")
    .replace(/\s/g, "");
  return base64ToBytes(body);
}

async function extractRsaPublicNumbers(publicKeyPem: string): Promise<{
  modulus: bigint;
  exponent: bigint;
  byteLength: number;
}> {
  const key = await crypto.subtle.importKey(
    "spki",
    pemToDer(publicKeyPem) as BufferSource,
    { name: "RSA-OAEP", hash: "SHA-256" },
    true,
    ["encrypt"],
  );
  const jwk = await crypto.subtle.exportKey("jwk", key);
  if (!jwk.n || !jwk.e) {
    throw new Error("Invalid RSA public key");
  }

  const modulusBytes = base64UrlToBytes(jwk.n);
  return {
    modulus: bytesToBigInt(modulusBytes),
    exponent: bytesToBigInt(base64UrlToBytes(jwk.e)),
    byteLength: modulusBytes.length,
  };
}

function pkcs1v15Encode(message: Uint8Array, keyByteLength: number): Uint8Array {
  if (message.length > keyByteLength - 11) {
    throw new Error("Login credential is too long for RSA encryption");
  }

  const paddingLength = keyByteLength - message.length - 3;
  const padding = new Uint8Array(paddingLength);
  let offset = 0;
  while (offset < padding.length) {
    const random = new Uint8Array(padding.length - offset);
    crypto.getRandomValues(random);
    for (const byte of random) {
      if (byte !== 0) {
        padding[offset] = byte;
        offset += 1;
        if (offset === padding.length) {
          break;
        }
      }
    }
  }

  const encoded = new Uint8Array(keyByteLength);
  encoded[0] = 0;
  encoded[1] = 2;
  encoded.set(padding, 2);
  encoded[2 + paddingLength] = 0;
  encoded.set(message, 3 + paddingLength);
  return encoded;
}

export async function encryptInsBaseCredential(
  value: string,
  publicKeyPem: string,
): Promise<string> {
  const { modulus, exponent, byteLength } = await extractRsaPublicNumbers(publicKeyPem);
  const message = new TextEncoder().encode(value);
  const encoded = pkcs1v15Encode(message, byteLength);
  const encrypted = modPow(bytesToBigInt(encoded), exponent, modulus);
  return bytesToBase64(bigIntToFixedBytes(encrypted, byteLength));
}
