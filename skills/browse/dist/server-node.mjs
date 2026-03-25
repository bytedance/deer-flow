import { createRequire } from "node:module";
// ── Windows Node.js compatibility (auto-generated) ──
import { fileURLToPath as _ftp } from "node:url";
import { dirname as _dn } from "node:path";
const __browseNodeSrcDir = _dn(_dn(_ftp(import.meta.url))) + "/src";
{ const _r = createRequire(import.meta.url); _r("./bun-polyfill.cjs"); }
// ── end compatibility ──
var __defProp = Object.defineProperty;
var __returnValue = (v) => v;
function __exportSetter(name, newValue) {
  this[name] = __returnValue.bind(null, newValue);
}
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, {
      get: all[name],
      enumerable: true,
      configurable: true,
      set: __exportSetter.bind(all, name)
    });
};
var __esm = (fn, res) => () => (fn && (res = fn(fn = 0)), res);
var __require = /* @__PURE__ */ createRequire(import.meta.url);

// browse/src/buffers.ts
class CircularBuffer {
  buffer;
  head = 0;
  _size = 0;
  _totalAdded = 0;
  capacity;
  constructor(capacity) {
    this.capacity = capacity;
    this.buffer = new Array(capacity);
  }
  push(entry) {
    const index = (this.head + this._size) % this.capacity;
    this.buffer[index] = entry;
    if (this._size < this.capacity) {
      this._size++;
    } else {
      this.head = (this.head + 1) % this.capacity;
    }
    this._totalAdded++;
  }
  toArray() {
    const result = [];
    for (let i = 0;i < this._size; i++) {
      result.push(this.buffer[(this.head + i) % this.capacity]);
    }
    return result;
  }
  last(n) {
    const count = Math.min(n, this._size);
    const result = [];
    const start = (this.head + this._size - count) % this.capacity;
    for (let i = 0;i < count; i++) {
      result.push(this.buffer[(start + i) % this.capacity]);
    }
    return result;
  }
  get length() {
    return this._size;
  }
  get totalAdded() {
    return this._totalAdded;
  }
  clear() {
    this.head = 0;
    this._size = 0;
  }
  get(index) {
    if (index < 0 || index >= this._size)
      return;
    return this.buffer[(this.head + index) % this.capacity];
  }
  set(index, entry) {
    if (index < 0 || index >= this._size)
      return;
    this.buffer[(this.head + index) % this.capacity] = entry;
  }
}
function addConsoleEntry(entry) {
  consoleBuffer.push(entry);
}
function addNetworkEntry(entry) {
  networkBuffer.push(entry);
}
function addDialogEntry(entry) {
  dialogBuffer.push(entry);
}
var HIGH_WATER_MARK = 50000, consoleBuffer, networkBuffer, dialogBuffer;
var init_buffers = __esm(() => {
  consoleBuffer = new CircularBuffer(HIGH_WATER_MARK);
  networkBuffer = new CircularBuffer(HIGH_WATER_MARK);
  dialogBuffer = new CircularBuffer(HIGH_WATER_MARK);
});

// browse/src/url-validation.ts
function normalizeHostname(hostname) {
  let h = hostname.startsWith("[") && hostname.endsWith("]") ? hostname.slice(1, -1) : hostname;
  if (h.endsWith("."))
    h = h.slice(0, -1);
  return h;
}
function isMetadataIp(hostname) {
  try {
    const probe = new URL(`http://${hostname}`);
    const normalized = probe.hostname;
    if (BLOCKED_METADATA_HOSTS.has(normalized))
      return true;
    if (normalized.endsWith(".") && BLOCKED_METADATA_HOSTS.has(normalized.slice(0, -1)))
      return true;
  } catch {}
  return false;
}
function validateNavigationUrl(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`Invalid URL: ${url}`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`Blocked: scheme "${parsed.protocol}" is not allowed. Only http: and https: URLs are permitted.`);
  }
  const hostname = normalizeHostname(parsed.hostname.toLowerCase());
  if (BLOCKED_METADATA_HOSTS.has(hostname) || isMetadataIp(hostname)) {
    throw new Error(`Blocked: ${parsed.hostname} is a cloud metadata endpoint. Access is denied for security.`);
  }
}
var BLOCKED_METADATA_HOSTS;
var init_url_validation = __esm(() => {
  BLOCKED_METADATA_HOSTS = new Set([
    "169.254.169.254",
    "fd00::",
    "metadata.google.internal"
  ]);
});

// browse/src/platform.ts
import * as os from "os";
import * as path from "path";
function isPathWithin(resolvedPath, dir) {
  return resolvedPath === dir || resolvedPath.startsWith(dir + path.sep);
}
var IS_WINDOWS, TEMP_DIR;
var init_platform = __esm(() => {
  IS_WINDOWS = process.platform === "win32";
  TEMP_DIR = IS_WINDOWS ? os.tmpdir() : "/tmp";
});

// browse/src/read-commands.ts
var exports_read_commands = {};
__export(exports_read_commands, {
  validateReadPath: () => validateReadPath,
  handleReadCommand: () => handleReadCommand,
  getCleanText: () => getCleanText
});
import * as fs from "fs";
import * as path2 from "path";
function hasAwait(code) {
  const stripped = code.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
  return /\bawait\b/.test(stripped);
}
function needsBlockWrapper(code) {
  const trimmed = code.trim();
  if (trimmed.split(`
`).length > 1)
    return true;
  if (/\b(const|let|var|function|class|return|throw|if|for|while|switch|try)\b/.test(trimmed))
    return true;
  if (trimmed.includes(";"))
    return true;
  return false;
}
function wrapForEvaluate(code) {
  if (!hasAwait(code))
    return code;
  const trimmed = code.trim();
  return needsBlockWrapper(trimmed) ? `(async()=>{
${code}
})()` : `(async()=>(${trimmed}))()`;
}
function validateReadPath(filePath) {
  if (path2.isAbsolute(filePath)) {
    const resolved = path2.resolve(filePath);
    const isSafe = SAFE_DIRECTORIES.some((dir) => isPathWithin(resolved, dir));
    if (!isSafe) {
      throw new Error(`Absolute path must be within: ${SAFE_DIRECTORIES.join(", ")}`);
    }
  }
  const normalized = path2.normalize(filePath);
  if (normalized.includes("..")) {
    throw new Error("Path traversal sequences (..) are not allowed");
  }
}
async function getCleanText(page) {
  return await page.evaluate(() => {
    const body = document.body;
    if (!body)
      return "";
    const clone = body.cloneNode(true);
    clone.querySelectorAll("script, style, noscript, svg").forEach((el) => el.remove());
    return clone.innerText.split(`
`).map((line) => line.trim()).filter((line) => line.length > 0).join(`
`);
  });
}
async function handleReadCommand(command, args, bm) {
  const page = bm.getPage();
  switch (command) {
    case "text": {
      return await getCleanText(page);
    }
    case "html": {
      const selector = args[0];
      if (selector) {
        const resolved = await bm.resolveRef(selector);
        if ("locator" in resolved) {
          return await resolved.locator.innerHTML({ timeout: 5000 });
        }
        return await page.innerHTML(resolved.selector);
      }
      return await page.content();
    }
    case "links": {
      const links = await page.evaluate(() => [...document.querySelectorAll("a[href]")].map((a) => ({
        text: a.textContent?.trim().slice(0, 120) || "",
        href: a.href
      })).filter((l) => l.text && l.href));
      return links.map((l) => `${l.text} → ${l.href}`).join(`
`);
    }
    case "forms": {
      const forms = await page.evaluate(() => {
        return [...document.querySelectorAll("form")].map((form, i) => {
          const fields = [...form.querySelectorAll("input, select, textarea")].map((el) => {
            const input = el;
            return {
              tag: el.tagName.toLowerCase(),
              type: input.type || undefined,
              name: input.name || undefined,
              id: input.id || undefined,
              placeholder: input.placeholder || undefined,
              required: input.required || undefined,
              value: input.type === "password" ? "[redacted]" : input.value || undefined,
              options: el.tagName === "SELECT" ? [...el.options].map((o) => ({ value: o.value, text: o.text })) : undefined
            };
          });
          return {
            index: i,
            action: form.action || undefined,
            method: form.method || "get",
            id: form.id || undefined,
            fields
          };
        });
      });
      return JSON.stringify(forms, null, 2);
    }
    case "accessibility": {
      const snapshot = await page.locator("body").ariaSnapshot();
      return snapshot;
    }
    case "js": {
      const expr = args[0];
      if (!expr)
        throw new Error("Usage: browse js <expression>");
      const wrapped = wrapForEvaluate(expr);
      const result = await page.evaluate(wrapped);
      return typeof result === "object" ? JSON.stringify(result, null, 2) : String(result ?? "");
    }
    case "eval": {
      const filePath = args[0];
      if (!filePath)
        throw new Error("Usage: browse eval <js-file>");
      validateReadPath(filePath);
      if (!fs.existsSync(filePath))
        throw new Error(`File not found: ${filePath}`);
      const code = fs.readFileSync(filePath, "utf-8");
      const wrapped = wrapForEvaluate(code);
      const result = await page.evaluate(wrapped);
      return typeof result === "object" ? JSON.stringify(result, null, 2) : String(result ?? "");
    }
    case "css": {
      const [selector, property] = args;
      if (!selector || !property)
        throw new Error("Usage: browse css <selector> <property>");
      const resolved = await bm.resolveRef(selector);
      if ("locator" in resolved) {
        const value2 = await resolved.locator.evaluate((el, prop) => getComputedStyle(el).getPropertyValue(prop), property);
        return value2;
      }
      const value = await page.evaluate(([sel, prop]) => {
        const el = document.querySelector(sel);
        if (!el)
          return `Element not found: ${sel}`;
        return getComputedStyle(el).getPropertyValue(prop);
      }, [resolved.selector, property]);
      return value;
    }
    case "attrs": {
      const selector = args[0];
      if (!selector)
        throw new Error("Usage: browse attrs <selector>");
      const resolved = await bm.resolveRef(selector);
      if ("locator" in resolved) {
        const attrs2 = await resolved.locator.evaluate((el) => {
          const result = {};
          for (const attr of el.attributes) {
            result[attr.name] = attr.value;
          }
          return result;
        });
        return JSON.stringify(attrs2, null, 2);
      }
      const attrs = await page.evaluate((sel) => {
        const el = document.querySelector(sel);
        if (!el)
          return `Element not found: ${sel}`;
        const result = {};
        for (const attr of el.attributes) {
          result[attr.name] = attr.value;
        }
        return result;
      }, resolved.selector);
      return typeof attrs === "string" ? attrs : JSON.stringify(attrs, null, 2);
    }
    case "console": {
      if (args[0] === "--clear") {
        consoleBuffer.clear();
        return "Console buffer cleared.";
      }
      const entries = args[0] === "--errors" ? consoleBuffer.toArray().filter((e) => e.level === "error" || e.level === "warning") : consoleBuffer.toArray();
      if (entries.length === 0)
        return args[0] === "--errors" ? "(no console errors)" : "(no console messages)";
      return entries.map((e) => `[${new Date(e.timestamp).toISOString()}] [${e.level}] ${e.text}`).join(`
`);
    }
    case "network": {
      if (args[0] === "--clear") {
        networkBuffer.clear();
        return "Network buffer cleared.";
      }
      if (networkBuffer.length === 0)
        return "(no network requests)";
      return networkBuffer.toArray().map((e) => `${e.method} ${e.url} → ${e.status || "pending"} (${e.duration || "?"}ms, ${e.size || "?"}B)`).join(`
`);
    }
    case "dialog": {
      if (args[0] === "--clear") {
        dialogBuffer.clear();
        return "Dialog buffer cleared.";
      }
      if (dialogBuffer.length === 0)
        return "(no dialogs captured)";
      return dialogBuffer.toArray().map((e) => `[${new Date(e.timestamp).toISOString()}] [${e.type}] "${e.message}" → ${e.action}${e.response ? ` "${e.response}"` : ""}`).join(`
`);
    }
    case "is": {
      const property = args[0];
      const selector = args[1];
      if (!property || !selector)
        throw new Error(`Usage: browse is <property> <selector>
Properties: visible, hidden, enabled, disabled, checked, editable, focused`);
      const resolved = await bm.resolveRef(selector);
      let locator;
      if ("locator" in resolved) {
        locator = resolved.locator;
      } else {
        locator = page.locator(resolved.selector);
      }
      switch (property) {
        case "visible":
          return String(await locator.isVisible());
        case "hidden":
          return String(await locator.isHidden());
        case "enabled":
          return String(await locator.isEnabled());
        case "disabled":
          return String(await locator.isDisabled());
        case "checked":
          return String(await locator.isChecked());
        case "editable":
          return String(await locator.isEditable());
        case "focused": {
          const isFocused = await locator.evaluate((el) => el === document.activeElement);
          return String(isFocused);
        }
        default:
          throw new Error(`Unknown property: ${property}. Use: visible, hidden, enabled, disabled, checked, editable, focused`);
      }
    }
    case "cookies": {
      const cookies = await page.context().cookies();
      return JSON.stringify(cookies, null, 2);
    }
    case "storage": {
      if (args[0] === "set" && args[1]) {
        const key = args[1];
        const value = args[2] || "";
        await page.evaluate(([k, v]) => localStorage.setItem(k, v), [key, value]);
        return `Set localStorage["${key}"]`;
      }
      const storage = await page.evaluate(() => ({
        localStorage: { ...localStorage },
        sessionStorage: { ...sessionStorage }
      }));
      return JSON.stringify(storage, null, 2);
    }
    case "perf": {
      const timings = await page.evaluate(() => {
        const nav = performance.getEntriesByType("navigation")[0];
        if (!nav)
          return "No navigation timing data available.";
        return {
          dns: Math.round(nav.domainLookupEnd - nav.domainLookupStart),
          tcp: Math.round(nav.connectEnd - nav.connectStart),
          ssl: Math.round(nav.secureConnectionStart > 0 ? nav.connectEnd - nav.secureConnectionStart : 0),
          ttfb: Math.round(nav.responseStart - nav.requestStart),
          download: Math.round(nav.responseEnd - nav.responseStart),
          domParse: Math.round(nav.domInteractive - nav.responseEnd),
          domReady: Math.round(nav.domContentLoadedEventEnd - nav.startTime),
          load: Math.round(nav.loadEventEnd - nav.startTime),
          total: Math.round(nav.loadEventEnd - nav.startTime)
        };
      });
      if (typeof timings === "string")
        return timings;
      return Object.entries(timings).map(([k, v]) => `${k.padEnd(12)} ${v}ms`).join(`
`);
    }
    default:
      throw new Error(`Unknown read command: ${command}`);
  }
}
var SAFE_DIRECTORIES;
var init_read_commands = __esm(() => {
  init_buffers();
  init_platform();
  SAFE_DIRECTORIES = [TEMP_DIR, process.cwd()];
});

// browse/src/cookie-import-browser.ts
const Database = null; // bun:sqlite stubbed on Node
import * as crypto from "crypto";
import * as fs2 from "fs";
import * as path3 from "path";
import * as os2 from "os";
function findInstalledBrowsers() {
  const appSupport = path3.join(os2.homedir(), "Library", "Application Support");
  return BROWSER_REGISTRY.filter((b) => {
    const dbPath = path3.join(appSupport, b.dataDir, "Default", "Cookies");
    try {
      return fs2.existsSync(dbPath);
    } catch {
      return false;
    }
  });
}
function listDomains(browserName, profile = "Default") {
  const browser = resolveBrowser(browserName);
  const dbPath = getCookieDbPath(browser, profile);
  const db = openDb(dbPath, browser.name);
  try {
    const now = chromiumNow();
    const rows = db.query(`SELECT host_key AS domain, COUNT(*) AS count
       FROM cookies
       WHERE has_expires = 0 OR expires_utc > ?
       GROUP BY host_key
       ORDER BY count DESC`).all(now);
    return { domains: rows, browser: browser.name };
  } finally {
    db.close();
  }
}
async function importCookies(browserName, domains, profile = "Default") {
  if (domains.length === 0)
    return { cookies: [], count: 0, failed: 0, domainCounts: {} };
  const browser = resolveBrowser(browserName);
  const derivedKey = await getDerivedKey(browser);
  const dbPath = getCookieDbPath(browser, profile);
  const db = openDb(dbPath, browser.name);
  try {
    const now = chromiumNow();
    const placeholders = domains.map(() => "?").join(",");
    const rows = db.query(`SELECT host_key, name, value, encrypted_value, path, expires_utc,
              is_secure, is_httponly, has_expires, samesite
       FROM cookies
       WHERE host_key IN (${placeholders})
         AND (has_expires = 0 OR expires_utc > ?)
       ORDER BY host_key, name`).all(...domains, now);
    const cookies = [];
    let failed = 0;
    const domainCounts = {};
    for (const row of rows) {
      try {
        const value = decryptCookieValue(row, derivedKey);
        const cookie = toPlaywrightCookie(row, value);
        cookies.push(cookie);
        domainCounts[row.host_key] = (domainCounts[row.host_key] || 0) + 1;
      } catch {
        failed++;
      }
    }
    return { cookies, count: cookies.length, failed, domainCounts };
  } finally {
    db.close();
  }
}
function resolveBrowser(nameOrAlias) {
  const needle = nameOrAlias.toLowerCase().trim();
  const found = BROWSER_REGISTRY.find((b) => b.aliases.includes(needle) || b.name.toLowerCase() === needle);
  if (!found) {
    const supported = BROWSER_REGISTRY.flatMap((b) => b.aliases).join(", ");
    throw new CookieImportError(`Unknown browser '${nameOrAlias}'. Supported: ${supported}`, "unknown_browser");
  }
  return found;
}
function validateProfile(profile) {
  if (/[/\\]|\.\./.test(profile) || /[\x00-\x1f]/.test(profile)) {
    throw new CookieImportError(`Invalid profile name: '${profile}'`, "bad_request");
  }
}
function getCookieDbPath(browser, profile) {
  validateProfile(profile);
  const appSupport = path3.join(os2.homedir(), "Library", "Application Support");
  const dbPath = path3.join(appSupport, browser.dataDir, profile, "Cookies");
  if (!fs2.existsSync(dbPath)) {
    throw new CookieImportError(`${browser.name} is not installed (no cookie database at ${dbPath})`, "not_installed");
  }
  return dbPath;
}
function openDb(dbPath, browserName) {
  try {
    return new Database(dbPath, { readonly: true });
  } catch (err) {
    if (err.message?.includes("SQLITE_BUSY") || err.message?.includes("database is locked")) {
      return openDbFromCopy(dbPath, browserName);
    }
    if (err.message?.includes("SQLITE_CORRUPT") || err.message?.includes("malformed")) {
      throw new CookieImportError(`Cookie database for ${browserName} is corrupt`, "db_corrupt");
    }
    throw err;
  }
}
function openDbFromCopy(dbPath, browserName) {
  const tmpPath = `/tmp/browse-cookies-${browserName.toLowerCase()}-${crypto.randomUUID()}.db`;
  try {
    fs2.copyFileSync(dbPath, tmpPath);
    const walPath = dbPath + "-wal";
    const shmPath = dbPath + "-shm";
    if (fs2.existsSync(walPath))
      fs2.copyFileSync(walPath, tmpPath + "-wal");
    if (fs2.existsSync(shmPath))
      fs2.copyFileSync(shmPath, tmpPath + "-shm");
    const db = new Database(tmpPath, { readonly: true });
    const origClose = db.close.bind(db);
    db.close = () => {
      origClose();
      try {
        fs2.unlinkSync(tmpPath);
      } catch {}
      try {
        fs2.unlinkSync(tmpPath + "-wal");
      } catch {}
      try {
        fs2.unlinkSync(tmpPath + "-shm");
      } catch {}
    };
    return db;
  } catch {
    try {
      fs2.unlinkSync(tmpPath);
    } catch {}
    throw new CookieImportError(`Cookie database is locked (${browserName} may be running). Try closing ${browserName} first.`, "db_locked", "retry");
  }
}
async function getDerivedKey(browser) {
  const cached = keyCache.get(browser.keychainService);
  if (cached)
    return cached;
  const password = await getKeychainPassword(browser.keychainService);
  const derived = crypto.pbkdf2Sync(password, "saltysalt", 1003, 16, "sha1");
  keyCache.set(browser.keychainService, derived);
  return derived;
}
async function getKeychainPassword(service) {
  const proc = Bun.spawn(["security", "find-generic-password", "-s", service, "-w"], { stdout: "pipe", stderr: "pipe" });
  const timeout = new Promise((_, reject) => setTimeout(() => {
    proc.kill();
    reject(new CookieImportError(`macOS is waiting for Keychain permission. Look for a dialog asking to allow access to "${service}".`, "keychain_timeout", "retry"));
  }, 1e4));
  try {
    const exitCode = await Promise.race([proc.exited, timeout]);
    const stdout = await new Response(proc.stdout).text();
    const stderr = await new Response(proc.stderr).text();
    if (exitCode !== 0) {
      const errText = stderr.trim().toLowerCase();
      if (errText.includes("user canceled") || errText.includes("denied") || errText.includes("interaction not allowed")) {
        throw new CookieImportError(`Keychain access denied. Click "Allow" in the macOS dialog for "${service}".`, "keychain_denied", "retry");
      }
      if (errText.includes("could not be found") || errText.includes("not found")) {
        throw new CookieImportError(`No Keychain entry for "${service}". Is this a Chromium-based browser?`, "keychain_not_found");
      }
      throw new CookieImportError(`Could not read Keychain: ${stderr.trim()}`, "keychain_error", "retry");
    }
    return stdout.trim();
  } catch (err) {
    if (err instanceof CookieImportError)
      throw err;
    throw new CookieImportError(`Could not read Keychain: ${err.message}`, "keychain_error", "retry");
  }
}
function decryptCookieValue(row, key) {
  if (row.value && row.value.length > 0)
    return row.value;
  const ev = Buffer.from(row.encrypted_value);
  if (ev.length === 0)
    return "";
  const prefix = ev.slice(0, 3).toString("utf-8");
  if (prefix !== "v10") {
    throw new Error(`Unknown encryption prefix: ${prefix}`);
  }
  const ciphertext = ev.slice(3);
  const iv = Buffer.alloc(16, 32);
  const decipher = crypto.createDecipheriv("aes-128-cbc", key, iv);
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  if (plaintext.length <= 32)
    return "";
  return plaintext.slice(32).toString("utf-8");
}
function toPlaywrightCookie(row, value) {
  return {
    name: row.name,
    value,
    domain: row.host_key,
    path: row.path || "/",
    expires: chromiumEpochToUnix(row.expires_utc, row.has_expires),
    secure: row.is_secure === 1,
    httpOnly: row.is_httponly === 1,
    sameSite: mapSameSite(row.samesite)
  };
}
function chromiumNow() {
  return BigInt(Date.now()) * 1000n + CHROMIUM_EPOCH_OFFSET;
}
function chromiumEpochToUnix(epoch, hasExpires) {
  if (hasExpires === 0 || epoch === 0 || epoch === 0n)
    return -1;
  const epochBig = BigInt(epoch);
  const unixMicro = epochBig - CHROMIUM_EPOCH_OFFSET;
  return Number(unixMicro / 1000000n);
}
function mapSameSite(value) {
  switch (value) {
    case 0:
      return "None";
    case 1:
      return "Lax";
    case 2:
      return "Strict";
    default:
      return "Lax";
  }
}
var CookieImportError, BROWSER_REGISTRY, keyCache, CHROMIUM_EPOCH_OFFSET = 11644473600000000n;
var init_cookie_import_browser = __esm(() => {
  CookieImportError = class CookieImportError extends Error {
    code;
    action;
    constructor(message, code, action) {
      super(message);
      this.code = code;
      this.action = action;
      this.name = "CookieImportError";
    }
  };
  BROWSER_REGISTRY = [
    { name: "Comet", dataDir: "Comet/", keychainService: "Comet Safe Storage", aliases: ["comet", "perplexity"] },
    { name: "Chrome", dataDir: "Google/Chrome/", keychainService: "Chrome Safe Storage", aliases: ["chrome", "google-chrome"] },
    { name: "Arc", dataDir: "Arc/User Data/", keychainService: "Arc Safe Storage", aliases: ["arc"] },
    { name: "Brave", dataDir: "BraveSoftware/Brave-Browser/", keychainService: "Brave Safe Storage", aliases: ["brave"] },
    { name: "Edge", dataDir: "Microsoft Edge/", keychainService: "Microsoft Edge Safe Storage", aliases: ["edge"] }
  ];
  keyCache = new Map;
});

// browse/src/write-commands.ts
var exports_write_commands = {};
__export(exports_write_commands, {
  handleWriteCommand: () => handleWriteCommand
});
import * as fs3 from "fs";
import * as path4 from "path";
async function handleWriteCommand(command, args, bm) {
  const page = bm.getPage();
  switch (command) {
    case "goto": {
      const url = args[0];
      if (!url)
        throw new Error("Usage: browse goto <url>");
      validateNavigationUrl(url);
      const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 15000 });
      const status = response?.status() || "unknown";
      return `Navigated to ${url} (${status})`;
    }
    case "back": {
      await page.goBack({ waitUntil: "domcontentloaded", timeout: 15000 });
      return `Back → ${page.url()}`;
    }
    case "forward": {
      await page.goForward({ waitUntil: "domcontentloaded", timeout: 15000 });
      return `Forward → ${page.url()}`;
    }
    case "reload": {
      await page.reload({ waitUntil: "domcontentloaded", timeout: 15000 });
      return `Reloaded ${page.url()}`;
    }
    case "click": {
      const selector = args[0];
      if (!selector)
        throw new Error("Usage: browse click <selector>");
      const role = bm.getRefRole(selector);
      if (role === "option") {
        const resolved2 = await bm.resolveRef(selector);
        if ("locator" in resolved2) {
          const optionInfo = await resolved2.locator.evaluate((el) => {
            if (el.tagName !== "OPTION")
              return null;
            const option = el;
            const select = option.closest("select");
            if (!select)
              return null;
            return { value: option.value, text: option.text };
          });
          if (optionInfo) {
            await resolved2.locator.locator("xpath=ancestor::select").selectOption(optionInfo.value, { timeout: 5000 });
            return `Selected "${optionInfo.text}" (auto-routed from click on <option>) → now at ${page.url()}`;
          }
        }
      }
      const resolved = await bm.resolveRef(selector);
      try {
        if ("locator" in resolved) {
          await resolved.locator.click({ timeout: 5000 });
        } else {
          await page.click(resolved.selector, { timeout: 5000 });
        }
      } catch (err) {
        const isOption = "locator" in resolved ? await resolved.locator.evaluate((el) => el.tagName === "OPTION").catch(() => false) : await page.evaluate((sel) => document.querySelector(sel)?.tagName === "OPTION", resolved.selector).catch(() => false);
        if (isOption) {
          throw new Error(`Cannot click <option> elements. Use 'browse select <parent-select> <value>' instead of 'click' for dropdown options.`);
        }
        throw err;
      }
      await page.waitForLoadState("domcontentloaded").catch(() => {});
      return `Clicked ${selector} → now at ${page.url()}`;
    }
    case "fill": {
      const [selector, ...valueParts] = args;
      const value = valueParts.join(" ");
      if (!selector || !value)
        throw new Error("Usage: browse fill <selector> <value>");
      const resolved = await bm.resolveRef(selector);
      if ("locator" in resolved) {
        await resolved.locator.fill(value, { timeout: 5000 });
      } else {
        await page.fill(resolved.selector, value, { timeout: 5000 });
      }
      return `Filled ${selector}`;
    }
    case "select": {
      const [selector, ...valueParts] = args;
      const value = valueParts.join(" ");
      if (!selector || !value)
        throw new Error("Usage: browse select <selector> <value>");
      const resolved = await bm.resolveRef(selector);
      if ("locator" in resolved) {
        await resolved.locator.selectOption(value, { timeout: 5000 });
      } else {
        await page.selectOption(resolved.selector, value, { timeout: 5000 });
      }
      return `Selected "${value}" in ${selector}`;
    }
    case "hover": {
      const selector = args[0];
      if (!selector)
        throw new Error("Usage: browse hover <selector>");
      const resolved = await bm.resolveRef(selector);
      if ("locator" in resolved) {
        await resolved.locator.hover({ timeout: 5000 });
      } else {
        await page.hover(resolved.selector, { timeout: 5000 });
      }
      return `Hovered ${selector}`;
    }
    case "type": {
      const text = args.join(" ");
      if (!text)
        throw new Error("Usage: browse type <text>");
      await page.keyboard.type(text);
      return `Typed ${text.length} characters`;
    }
    case "press": {
      const key = args[0];
      if (!key)
        throw new Error("Usage: browse press <key> (e.g., Enter, Tab, Escape)");
      await page.keyboard.press(key);
      return `Pressed ${key}`;
    }
    case "scroll": {
      const selector = args[0];
      if (selector) {
        const resolved = await bm.resolveRef(selector);
        if ("locator" in resolved) {
          await resolved.locator.scrollIntoViewIfNeeded({ timeout: 5000 });
        } else {
          await page.locator(resolved.selector).scrollIntoViewIfNeeded({ timeout: 5000 });
        }
        return `Scrolled ${selector} into view`;
      }
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      return "Scrolled to bottom";
    }
    case "wait": {
      const selector = args[0];
      if (!selector)
        throw new Error("Usage: browse wait <selector|--networkidle|--load|--domcontentloaded>");
      if (selector === "--networkidle") {
        const timeout2 = args[1] ? parseInt(args[1], 10) : 15000;
        await page.waitForLoadState("networkidle", { timeout: timeout2 });
        return "Network idle";
      }
      if (selector === "--load") {
        await page.waitForLoadState("load");
        return "Page loaded";
      }
      if (selector === "--domcontentloaded") {
        await page.waitForLoadState("domcontentloaded");
        return "DOM content loaded";
      }
      const timeout = args[1] ? parseInt(args[1], 10) : 15000;
      const resolved = await bm.resolveRef(selector);
      if ("locator" in resolved) {
        await resolved.locator.waitFor({ state: "visible", timeout });
      } else {
        await page.waitForSelector(resolved.selector, { timeout });
      }
      return `Element ${selector} appeared`;
    }
    case "viewport": {
      const size = args[0];
      if (!size || !size.includes("x"))
        throw new Error("Usage: browse viewport <WxH> (e.g., 375x812)");
      const [w, h] = size.split("x").map(Number);
      await bm.setViewport(w, h);
      return `Viewport set to ${w}x${h}`;
    }
    case "cookie": {
      const cookieStr = args[0];
      if (!cookieStr || !cookieStr.includes("="))
        throw new Error("Usage: browse cookie <name>=<value>");
      const eq = cookieStr.indexOf("=");
      const name = cookieStr.slice(0, eq);
      const value = cookieStr.slice(eq + 1);
      const url = new URL(page.url());
      await page.context().addCookies([{
        name,
        value,
        domain: url.hostname,
        path: "/"
      }]);
      return `Cookie set: ${name}=****`;
    }
    case "header": {
      const headerStr = args[0];
      if (!headerStr || !headerStr.includes(":"))
        throw new Error("Usage: browse header <name>:<value>");
      const sep2 = headerStr.indexOf(":");
      const name = headerStr.slice(0, sep2).trim();
      const value = headerStr.slice(sep2 + 1).trim();
      await bm.setExtraHeader(name, value);
      const sensitiveHeaders = ["authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token"];
      const redactedValue = sensitiveHeaders.includes(name.toLowerCase()) ? "****" : value;
      return `Header set: ${name}: ${redactedValue}`;
    }
    case "useragent": {
      const ua = args.join(" ");
      if (!ua)
        throw new Error("Usage: browse useragent <string>");
      bm.setUserAgent(ua);
      const error = await bm.recreateContext();
      if (error) {
        return `User agent set to "${ua}" but: ${error}`;
      }
      return `User agent set: ${ua}`;
    }
    case "upload": {
      const [selector, ...filePaths] = args;
      if (!selector || filePaths.length === 0)
        throw new Error("Usage: browse upload <selector> <file1> [file2...]");
      for (const fp of filePaths) {
        if (!fs3.existsSync(fp))
          throw new Error(`File not found: ${fp}`);
      }
      const resolved = await bm.resolveRef(selector);
      if ("locator" in resolved) {
        await resolved.locator.setInputFiles(filePaths);
      } else {
        await page.locator(resolved.selector).setInputFiles(filePaths);
      }
      const fileInfo = filePaths.map((fp) => {
        const stat = fs3.statSync(fp);
        return `${path4.basename(fp)} (${stat.size}B)`;
      }).join(", ");
      return `Uploaded: ${fileInfo}`;
    }
    case "dialog-accept": {
      const text = args.length > 0 ? args.join(" ") : null;
      bm.setDialogAutoAccept(true);
      bm.setDialogPromptText(text);
      return text ? `Dialogs will be accepted with text: "${text}"` : "Dialogs will be accepted";
    }
    case "dialog-dismiss": {
      bm.setDialogAutoAccept(false);
      bm.setDialogPromptText(null);
      return "Dialogs will be dismissed";
    }
    case "cookie-import": {
      const filePath = args[0];
      if (!filePath)
        throw new Error("Usage: browse cookie-import <json-file>");
      if (path4.isAbsolute(filePath)) {
        const safeDirs = [TEMP_DIR, process.cwd()];
        const resolved = path4.resolve(filePath);
        if (!safeDirs.some((dir) => isPathWithin(resolved, dir))) {
          throw new Error(`Path must be within: ${safeDirs.join(", ")}`);
        }
      }
      if (path4.normalize(filePath).includes("..")) {
        throw new Error("Path traversal sequences (..) are not allowed");
      }
      if (!fs3.existsSync(filePath))
        throw new Error(`File not found: ${filePath}`);
      const raw = fs3.readFileSync(filePath, "utf-8");
      let cookies;
      try {
        cookies = JSON.parse(raw);
      } catch {
        throw new Error(`Invalid JSON in ${filePath}`);
      }
      if (!Array.isArray(cookies))
        throw new Error("Cookie file must contain a JSON array");
      const pageUrl = new URL(page.url());
      const defaultDomain = pageUrl.hostname;
      for (const c of cookies) {
        if (!c.name || c.value === undefined)
          throw new Error('Each cookie must have "name" and "value" fields');
        if (!c.domain)
          c.domain = defaultDomain;
        if (!c.path)
          c.path = "/";
      }
      await page.context().addCookies(cookies);
      return `Loaded ${cookies.length} cookies from ${filePath}`;
    }
    case "cookie-import-browser": {
      const browserArg = args[0];
      const domainIdx = args.indexOf("--domain");
      if (domainIdx !== -1 && domainIdx + 1 < args.length) {
        const domain = args[domainIdx + 1];
        const browser = browserArg || "comet";
        const result = await importCookies(browser, [domain]);
        if (result.cookies.length > 0) {
          await page.context().addCookies(result.cookies);
        }
        const msg = [`Imported ${result.count} cookies for ${domain} from ${browser}`];
        if (result.failed > 0)
          msg.push(`(${result.failed} failed to decrypt)`);
        return msg.join(" ");
      }
      const port = bm.serverPort;
      if (!port)
        throw new Error("Server port not available");
      const browsers = findInstalledBrowsers();
      if (browsers.length === 0) {
        throw new Error("No Chromium browsers found. Supported: Comet, Chrome, Arc, Brave, Edge");
      }
      const pickerUrl = `http://127.0.0.1:${port}/cookie-picker`;
      try {
        Bun.spawn(["open", pickerUrl], { stdout: "ignore", stderr: "ignore" });
      } catch {}
      return `Cookie picker opened at ${pickerUrl}
Detected browsers: ${browsers.map((b) => b.name).join(", ")}
Select domains to import, then close the picker when done.`;
    }
    default:
      throw new Error(`Unknown write command: ${command}`);
  }
}
var init_write_commands = __esm(() => {
  init_cookie_import_browser();
  init_url_validation();
  init_platform();
});

// browse/src/browser-manager.ts
init_buffers();
init_url_validation();
import { chromium } from "playwright";

class BrowserManager {
  browser = null;
  context = null;
  pages = new Map;
  activeTabId = 0;
  nextTabId = 1;
  extraHeaders = {};
  customUserAgent = null;
  serverPort = 0;
  refMap = new Map;
  lastSnapshot = null;
  dialogAutoAccept = true;
  dialogPromptText = null;
  isHeaded = false;
  consecutiveFailures = 0;
  async launch() {
    this.browser = await chromium.launch({ headless: true });
    this.browser.on("disconnected", () => {
      console.error("[browse] FATAL: Chromium process crashed or was killed. Server exiting.");
      console.error("[browse] Console/network logs flushed to .gstack/browse-*.log");
      process.exit(1);
    });
    const contextOptions = {
      viewport: { width: 1280, height: 720 }
    };
    if (this.customUserAgent) {
      contextOptions.userAgent = this.customUserAgent;
    }
    this.context = await this.browser.newContext(contextOptions);
    if (Object.keys(this.extraHeaders).length > 0) {
      await this.context.setExtraHTTPHeaders(this.extraHeaders);
    }
    await this.newTab();
  }
  async close() {
    if (this.browser) {
      this.browser.removeAllListeners("disconnected");
      await Promise.race([
        this.browser.close(),
        new Promise((resolve) => setTimeout(resolve, 5000))
      ]).catch(() => {});
      this.browser = null;
    }
  }
  async isHealthy() {
    if (!this.browser || !this.browser.isConnected())
      return false;
    try {
      const page = this.pages.get(this.activeTabId);
      if (!page)
        return true;
      await Promise.race([
        page.evaluate("1"),
        new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 2000))
      ]);
      return true;
    } catch {
      return false;
    }
  }
  async newTab(url) {
    if (!this.context)
      throw new Error("Browser not launched");
    if (url) {
      validateNavigationUrl(url);
    }
    const page = await this.context.newPage();
    const id = this.nextTabId++;
    this.pages.set(id, page);
    this.activeTabId = id;
    this.wirePageEvents(page);
    if (url) {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 15000 });
    }
    return id;
  }
  async closeTab(id) {
    const tabId = id ?? this.activeTabId;
    const page = this.pages.get(tabId);
    if (!page)
      throw new Error(`Tab ${tabId} not found`);
    await page.close();
    this.pages.delete(tabId);
    if (tabId === this.activeTabId) {
      const remaining = [...this.pages.keys()];
      if (remaining.length > 0) {
        this.activeTabId = remaining[remaining.length - 1];
      } else {
        await this.newTab();
      }
    }
  }
  switchTab(id) {
    if (!this.pages.has(id))
      throw new Error(`Tab ${id} not found`);
    this.activeTabId = id;
  }
  getTabCount() {
    return this.pages.size;
  }
  async getTabListWithTitles() {
    const tabs = [];
    for (const [id, page] of this.pages) {
      tabs.push({
        id,
        url: page.url(),
        title: await page.title().catch(() => ""),
        active: id === this.activeTabId
      });
    }
    return tabs;
  }
  getPage() {
    const page = this.pages.get(this.activeTabId);
    if (!page)
      throw new Error('No active page. Use "browse goto <url>" first.');
    return page;
  }
  getCurrentUrl() {
    try {
      return this.getPage().url();
    } catch {
      return "about:blank";
    }
  }
  setRefMap(refs) {
    this.refMap = refs;
  }
  clearRefs() {
    this.refMap.clear();
  }
  async resolveRef(selector) {
    if (selector.startsWith("@e") || selector.startsWith("@c")) {
      const ref = selector.slice(1);
      const entry = this.refMap.get(ref);
      if (!entry) {
        throw new Error(`Ref ${selector} not found. Run 'snapshot' to get fresh refs.`);
      }
      const count = await entry.locator.count();
      if (count === 0) {
        throw new Error(`Ref ${selector} (${entry.role} "${entry.name}") is stale — element no longer exists. ` + `Run 'snapshot' for fresh refs.`);
      }
      return { locator: entry.locator };
    }
    return { selector };
  }
  getRefRole(selector) {
    if (selector.startsWith("@e") || selector.startsWith("@c")) {
      const entry = this.refMap.get(selector.slice(1));
      return entry?.role ?? null;
    }
    return null;
  }
  getRefCount() {
    return this.refMap.size;
  }
  setLastSnapshot(text) {
    this.lastSnapshot = text;
  }
  getLastSnapshot() {
    return this.lastSnapshot;
  }
  setDialogAutoAccept(accept) {
    this.dialogAutoAccept = accept;
  }
  getDialogAutoAccept() {
    return this.dialogAutoAccept;
  }
  setDialogPromptText(text) {
    this.dialogPromptText = text;
  }
  getDialogPromptText() {
    return this.dialogPromptText;
  }
  async setViewport(width, height) {
    await this.getPage().setViewportSize({ width, height });
  }
  async setExtraHeader(name, value) {
    this.extraHeaders[name] = value;
    if (this.context) {
      await this.context.setExtraHTTPHeaders(this.extraHeaders);
    }
  }
  setUserAgent(ua) {
    this.customUserAgent = ua;
  }
  getUserAgent() {
    return this.customUserAgent;
  }
  async saveState() {
    if (!this.context)
      throw new Error("Browser not launched");
    const cookies = await this.context.cookies();
    const pages = [];
    for (const [id, page] of this.pages) {
      const url = page.url();
      let storage = null;
      try {
        storage = await page.evaluate(() => ({
          localStorage: { ...localStorage },
          sessionStorage: { ...sessionStorage }
        }));
      } catch {}
      pages.push({
        url: url === "about:blank" ? "" : url,
        isActive: id === this.activeTabId,
        storage
      });
    }
    return { cookies, pages };
  }
  async restoreState(state) {
    if (!this.context)
      throw new Error("Browser not launched");
    if (state.cookies.length > 0) {
      await this.context.addCookies(state.cookies);
    }
    let activeId = null;
    for (const saved of state.pages) {
      const page = await this.context.newPage();
      const id = this.nextTabId++;
      this.pages.set(id, page);
      this.wirePageEvents(page);
      if (saved.url) {
        await page.goto(saved.url, { waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => {});
      }
      if (saved.storage) {
        try {
          await page.evaluate((s) => {
            if (s.localStorage) {
              for (const [k, v] of Object.entries(s.localStorage)) {
                localStorage.setItem(k, v);
              }
            }
            if (s.sessionStorage) {
              for (const [k, v] of Object.entries(s.sessionStorage)) {
                sessionStorage.setItem(k, v);
              }
            }
          }, saved.storage);
        } catch {}
      }
      if (saved.isActive)
        activeId = id;
    }
    if (this.pages.size === 0) {
      await this.newTab();
    } else {
      this.activeTabId = activeId ?? [...this.pages.keys()][0];
    }
    this.clearRefs();
  }
  async recreateContext() {
    if (!this.browser || !this.context) {
      throw new Error("Browser not launched");
    }
    try {
      const state = await this.saveState();
      for (const page of this.pages.values()) {
        await page.close().catch(() => {});
      }
      this.pages.clear();
      await this.context.close().catch(() => {});
      const contextOptions = {
        viewport: { width: 1280, height: 720 }
      };
      if (this.customUserAgent) {
        contextOptions.userAgent = this.customUserAgent;
      }
      this.context = await this.browser.newContext(contextOptions);
      if (Object.keys(this.extraHeaders).length > 0) {
        await this.context.setExtraHTTPHeaders(this.extraHeaders);
      }
      await this.restoreState(state);
      return null;
    } catch (err) {
      try {
        this.pages.clear();
        if (this.context)
          await this.context.close().catch(() => {});
        const contextOptions = {
          viewport: { width: 1280, height: 720 }
        };
        if (this.customUserAgent) {
          contextOptions.userAgent = this.customUserAgent;
        }
        this.context = await this.browser.newContext(contextOptions);
        await this.newTab();
        this.clearRefs();
      } catch {}
      return `Context recreation failed: ${err instanceof Error ? err.message : String(err)}. Browser reset to blank tab.`;
    }
  }
  async handoff(message) {
    if (this.isHeaded) {
      return `HANDOFF: Already in headed mode at ${this.getCurrentUrl()}`;
    }
    if (!this.browser || !this.context) {
      throw new Error("Browser not launched");
    }
    const state = await this.saveState();
    const currentUrl = this.getCurrentUrl();
    let newBrowser;
    try {
      newBrowser = await chromium.launch({ headless: false, timeout: 15000 });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return `ERROR: Cannot open headed browser — ${msg}. Headless browser still running.`;
    }
    try {
      const contextOptions = {
        viewport: { width: 1280, height: 720 }
      };
      if (this.customUserAgent) {
        contextOptions.userAgent = this.customUserAgent;
      }
      const newContext = await newBrowser.newContext(contextOptions);
      if (Object.keys(this.extraHeaders).length > 0) {
        await newContext.setExtraHTTPHeaders(this.extraHeaders);
      }
      const oldBrowser = this.browser;
      const oldContext = this.context;
      this.browser = newBrowser;
      this.context = newContext;
      this.pages.clear();
      this.browser.on("disconnected", () => {
        console.error("[browse] FATAL: Chromium process crashed or was killed. Server exiting.");
        console.error("[browse] Console/network logs flushed to .gstack/browse-*.log");
        process.exit(1);
      });
      await this.restoreState(state);
      this.isHeaded = true;
      oldBrowser.removeAllListeners("disconnected");
      oldBrowser.close().catch(() => {});
      return [
        `HANDOFF: Browser opened at ${currentUrl}`,
        `MESSAGE: ${message}`,
        `STATUS: Waiting for user. Run 'resume' when done.`
      ].join(`
`);
    } catch (err) {
      await newBrowser.close().catch(() => {});
      const msg = err instanceof Error ? err.message : String(err);
      return `ERROR: Handoff failed during state restore — ${msg}. Headless browser still running.`;
    }
  }
  resume() {
    this.clearRefs();
    this.resetFailures();
  }
  getIsHeaded() {
    return this.isHeaded;
  }
  incrementFailures() {
    this.consecutiveFailures++;
  }
  resetFailures() {
    this.consecutiveFailures = 0;
  }
  getFailureHint() {
    if (this.consecutiveFailures >= 3 && !this.isHeaded) {
      return `HINT: ${this.consecutiveFailures} consecutive failures. Consider using 'handoff' to let the user help.`;
    }
    return null;
  }
  wirePageEvents(page) {
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) {
        this.clearRefs();
      }
    });
    page.on("dialog", async (dialog) => {
      const entry = {
        timestamp: Date.now(),
        type: dialog.type(),
        message: dialog.message(),
        defaultValue: dialog.defaultValue() || undefined,
        action: this.dialogAutoAccept ? "accepted" : "dismissed",
        response: this.dialogAutoAccept ? this.dialogPromptText ?? undefined : undefined
      };
      addDialogEntry(entry);
      try {
        if (this.dialogAutoAccept) {
          await dialog.accept(this.dialogPromptText ?? undefined);
        } else {
          await dialog.dismiss();
        }
      } catch {}
    });
    page.on("console", (msg) => {
      addConsoleEntry({
        timestamp: Date.now(),
        level: msg.type(),
        text: msg.text()
      });
    });
    page.on("request", (req) => {
      addNetworkEntry({
        timestamp: Date.now(),
        method: req.method(),
        url: req.url()
      });
    });
    page.on("response", (res) => {
      const url = res.url();
      const status = res.status();
      for (let i = networkBuffer.length - 1;i >= 0; i--) {
        const entry = networkBuffer.get(i);
        if (entry && entry.url === url && !entry.status) {
          networkBuffer.set(i, { ...entry, status, duration: Date.now() - entry.timestamp });
          break;
        }
      }
    });
    page.on("requestfinished", async (req) => {
      try {
        const res = await req.response();
        if (res) {
          const url = req.url();
          const body = await res.body().catch(() => null);
          const size = body ? body.length : 0;
          for (let i = networkBuffer.length - 1;i >= 0; i--) {
            const entry = networkBuffer.get(i);
            if (entry && entry.url === url && !entry.size) {
              networkBuffer.set(i, { ...entry, size });
              break;
            }
          }
        }
      } catch {}
    });
  }
}

// browse/src/server.ts
init_read_commands();
init_write_commands();

// browse/src/snapshot.ts
init_platform();
import * as Diff from "diff";
var INTERACTIVE_ROLES = new Set([
  "button",
  "link",
  "textbox",
  "checkbox",
  "radio",
  "combobox",
  "listbox",
  "menuitem",
  "menuitemcheckbox",
  "menuitemradio",
  "option",
  "searchbox",
  "slider",
  "spinbutton",
  "switch",
  "tab",
  "treeitem"
]);
var SNAPSHOT_FLAGS = [
  { short: "-i", long: "--interactive", description: "Interactive elements only (buttons, links, inputs) with @e refs", optionKey: "interactive" },
  { short: "-c", long: "--compact", description: "Compact (no empty structural nodes)", optionKey: "compact" },
  { short: "-d", long: "--depth", description: "Limit tree depth (0 = root only, default: unlimited)", takesValue: true, valueHint: "<N>", optionKey: "depth" },
  { short: "-s", long: "--selector", description: "Scope to CSS selector", takesValue: true, valueHint: "<sel>", optionKey: "selector" },
  { short: "-D", long: "--diff", description: "Unified diff against previous snapshot (first call stores baseline)", optionKey: "diff" },
  { short: "-a", long: "--annotate", description: "Annotated screenshot with red overlay boxes and ref labels", optionKey: "annotate" },
  { short: "-o", long: "--output", description: "Output path for annotated screenshot (default: <temp>/browse-annotated.png)", takesValue: true, valueHint: "<path>", optionKey: "outputPath" },
  { short: "-C", long: "--cursor-interactive", description: "Cursor-interactive elements (@c refs — divs with pointer, onclick)", optionKey: "cursorInteractive" }
];
function parseSnapshotArgs(args) {
  const opts = {};
  for (let i = 0;i < args.length; i++) {
    const flag = SNAPSHOT_FLAGS.find((f) => f.short === args[i] || f.long === args[i]);
    if (!flag)
      throw new Error(`Unknown snapshot flag: ${args[i]}`);
    if (flag.takesValue) {
      const value = args[++i];
      if (!value)
        throw new Error(`Usage: snapshot ${flag.short} <value>`);
      if (flag.optionKey === "depth") {
        opts[flag.optionKey] = parseInt(value, 10);
        if (isNaN(opts.depth))
          throw new Error("Usage: snapshot -d <number>");
      } else {
        opts[flag.optionKey] = value;
      }
    } else {
      opts[flag.optionKey] = true;
    }
  }
  return opts;
}
function parseLine(line) {
  const match = line.match(/^(\s*)-\s+(\w+)(?:\s+"([^"]*)")?(?:\s+(\[.*?\]))?\s*(?::\s*(.*))?$/);
  if (!match) {
    return null;
  }
  return {
    indent: match[1].length,
    role: match[2],
    name: match[3] ?? null,
    props: match[4] || "",
    children: match[5]?.trim() || "",
    rawLine: line
  };
}
async function handleSnapshot(args, bm) {
  const opts = parseSnapshotArgs(args);
  const page = bm.getPage();
  let rootLocator;
  if (opts.selector) {
    rootLocator = page.locator(opts.selector);
    const count = await rootLocator.count();
    if (count === 0)
      throw new Error(`Selector not found: ${opts.selector}`);
  } else {
    rootLocator = page.locator("body");
  }
  const ariaText = await rootLocator.ariaSnapshot();
  if (!ariaText || ariaText.trim().length === 0) {
    bm.setRefMap(new Map);
    return "(no accessible elements found)";
  }
  const lines = ariaText.split(`
`);
  const refMap = new Map;
  const output = [];
  let refCounter = 1;
  const roleNameCounts = new Map;
  const roleNameSeen = new Map;
  for (const line of lines) {
    const node = parseLine(line);
    if (!node)
      continue;
    const key = `${node.role}:${node.name || ""}`;
    roleNameCounts.set(key, (roleNameCounts.get(key) || 0) + 1);
  }
  for (const line of lines) {
    const node = parseLine(line);
    if (!node)
      continue;
    const depth = Math.floor(node.indent / 2);
    const isInteractive = INTERACTIVE_ROLES.has(node.role);
    if (opts.depth !== undefined && depth > opts.depth)
      continue;
    if (opts.interactive && !isInteractive) {
      const key2 = `${node.role}:${node.name || ""}`;
      roleNameSeen.set(key2, (roleNameSeen.get(key2) || 0) + 1);
      continue;
    }
    if (opts.compact && !isInteractive && !node.name && !node.children)
      continue;
    const ref = `e${refCounter++}`;
    const indent = "  ".repeat(depth);
    const key = `${node.role}:${node.name || ""}`;
    const seenIndex = roleNameSeen.get(key) || 0;
    roleNameSeen.set(key, seenIndex + 1);
    const totalCount = roleNameCounts.get(key) || 1;
    let locator;
    if (opts.selector) {
      locator = page.locator(opts.selector).getByRole(node.role, {
        name: node.name || undefined
      });
    } else {
      locator = page.getByRole(node.role, {
        name: node.name || undefined
      });
    }
    if (totalCount > 1) {
      locator = locator.nth(seenIndex);
    }
    refMap.set(ref, { locator, role: node.role, name: node.name || "" });
    let outputLine = `${indent}@${ref} [${node.role}]`;
    if (node.name)
      outputLine += ` "${node.name}"`;
    if (node.props)
      outputLine += ` ${node.props}`;
    if (node.children)
      outputLine += `: ${node.children}`;
    output.push(outputLine);
  }
  if (opts.cursorInteractive) {
    try {
      const cursorElements = await page.evaluate(() => {
        const STANDARD_INTERACTIVE = new Set([
          "A",
          "BUTTON",
          "INPUT",
          "SELECT",
          "TEXTAREA",
          "SUMMARY",
          "DETAILS"
        ]);
        const results = [];
        const allElements = document.querySelectorAll("*");
        for (const el of allElements) {
          if (STANDARD_INTERACTIVE.has(el.tagName))
            continue;
          if (!el.offsetParent && el.tagName !== "BODY")
            continue;
          const style = getComputedStyle(el);
          const hasCursorPointer = style.cursor === "pointer";
          const hasOnclick = el.hasAttribute("onclick");
          const hasTabindex = el.hasAttribute("tabindex") && parseInt(el.getAttribute("tabindex"), 10) >= 0;
          const hasRole = el.hasAttribute("role");
          if (!hasCursorPointer && !hasOnclick && !hasTabindex)
            continue;
          if (hasRole)
            continue;
          const parts = [];
          let current = el;
          while (current && current !== document.documentElement) {
            const parent = current.parentElement;
            if (!parent)
              break;
            const siblings = [...parent.children];
            const index = siblings.indexOf(current) + 1;
            parts.unshift(`${current.tagName.toLowerCase()}:nth-child(${index})`);
            current = parent;
          }
          const selector = parts.join(" > ");
          const text = el.innerText?.trim().slice(0, 80) || el.tagName.toLowerCase();
          const reasons = [];
          if (hasCursorPointer)
            reasons.push("cursor:pointer");
          if (hasOnclick)
            reasons.push("onclick");
          if (hasTabindex)
            reasons.push(`tabindex=${el.getAttribute("tabindex")}`);
          results.push({ selector, text, reason: reasons.join(", ") });
        }
        return results;
      });
      if (cursorElements.length > 0) {
        output.push("");
        output.push("── cursor-interactive (not in ARIA tree) ──");
        let cRefCounter = 1;
        for (const elem of cursorElements) {
          const ref = `c${cRefCounter++}`;
          const locator = page.locator(elem.selector);
          refMap.set(ref, { locator, role: "cursor-interactive", name: elem.text });
          output.push(`@${ref} [${elem.reason}] "${elem.text}"`);
        }
      }
    } catch {
      output.push("");
      output.push("(cursor scan failed — CSP restriction)");
    }
  }
  bm.setRefMap(refMap);
  if (output.length === 0) {
    return "(no interactive elements found)";
  }
  const snapshotText = output.join(`
`);
  if (opts.annotate) {
    const screenshotPath = opts.outputPath || `${TEMP_DIR}/browse-annotated.png`;
    const resolvedPath = __require("path").resolve(screenshotPath);
    const safeDirs = [TEMP_DIR, process.cwd()];
    if (!safeDirs.some((dir) => isPathWithin(resolvedPath, dir))) {
      throw new Error(`Path must be within: ${safeDirs.join(", ")}`);
    }
    try {
      const boxes = [];
      for (const [ref, entry] of refMap) {
        try {
          const box = await entry.locator.boundingBox({ timeout: 1000 });
          if (box) {
            boxes.push({ ref: `@${ref}`, box });
          }
        } catch {}
      }
      await page.evaluate((boxes2) => {
        for (const { ref, box } of boxes2) {
          const overlay = document.createElement("div");
          overlay.className = "__browse_annotation__";
          overlay.style.cssText = `
            position: absolute; top: ${box.y}px; left: ${box.x}px;
            width: ${box.width}px; height: ${box.height}px;
            border: 2px solid red; background: rgba(255,0,0,0.1);
            pointer-events: none; z-index: 99999;
            font-size: 10px; color: red; font-weight: bold;
          `;
          const label = document.createElement("span");
          label.textContent = ref;
          label.style.cssText = "position: absolute; top: -14px; left: 0; background: red; color: white; padding: 0 3px; font-size: 10px;";
          overlay.appendChild(label);
          document.body.appendChild(overlay);
        }
      }, boxes);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      await page.evaluate(() => {
        document.querySelectorAll(".__browse_annotation__").forEach((el) => el.remove());
      });
      output.push("");
      output.push(`[annotated screenshot: ${screenshotPath}]`);
    } catch {
      try {
        await page.evaluate(() => {
          document.querySelectorAll(".__browse_annotation__").forEach((el) => el.remove());
        });
      } catch {}
    }
  }
  if (opts.diff) {
    const lastSnapshot = bm.getLastSnapshot();
    if (!lastSnapshot) {
      bm.setLastSnapshot(snapshotText);
      return snapshotText + `

(no previous snapshot to diff against — this snapshot stored as baseline)`;
    }
    const changes = Diff.diffLines(lastSnapshot, snapshotText);
    const diffOutput = ["--- previous snapshot", "+++ current snapshot", ""];
    for (const part of changes) {
      const prefix = part.added ? "+" : part.removed ? "-" : " ";
      const diffLines2 = part.value.split(`
`).filter((l) => l.length > 0);
      for (const line of diffLines2) {
        diffOutput.push(`${prefix} ${line}`);
      }
    }
    bm.setLastSnapshot(snapshotText);
    return diffOutput.join(`
`);
  }
  bm.setLastSnapshot(snapshotText);
  return output.join(`
`);
}

// browse/src/meta-commands.ts
init_read_commands();

// browse/src/commands.ts
var READ_COMMANDS = new Set([
  "text",
  "html",
  "links",
  "forms",
  "accessibility",
  "js",
  "eval",
  "css",
  "attrs",
  "console",
  "network",
  "cookies",
  "storage",
  "perf",
  "dialog",
  "is"
]);
var WRITE_COMMANDS = new Set([
  "goto",
  "back",
  "forward",
  "reload",
  "click",
  "fill",
  "select",
  "hover",
  "type",
  "press",
  "scroll",
  "wait",
  "viewport",
  "cookie",
  "cookie-import",
  "cookie-import-browser",
  "header",
  "useragent",
  "upload",
  "dialog-accept",
  "dialog-dismiss"
]);
var META_COMMANDS = new Set([
  "tabs",
  "tab",
  "newtab",
  "closetab",
  "status",
  "stop",
  "restart",
  "screenshot",
  "pdf",
  "responsive",
  "chain",
  "diff",
  "url",
  "snapshot",
  "handoff",
  "resume"
]);
var ALL_COMMANDS = new Set([...READ_COMMANDS, ...WRITE_COMMANDS, ...META_COMMANDS]);
var COMMAND_DESCRIPTIONS = {
  goto: { category: "Navigation", description: "Navigate to URL", usage: "goto <url>" },
  back: { category: "Navigation", description: "History back" },
  forward: { category: "Navigation", description: "History forward" },
  reload: { category: "Navigation", description: "Reload page" },
  url: { category: "Navigation", description: "Print current URL" },
  text: { category: "Reading", description: "Cleaned page text" },
  html: { category: "Reading", description: "innerHTML of selector (throws if not found), or full page HTML if no selector given", usage: "html [selector]" },
  links: { category: "Reading", description: 'All links as "text → href"' },
  forms: { category: "Reading", description: "Form fields as JSON" },
  accessibility: { category: "Reading", description: "Full ARIA tree" },
  js: { category: "Inspection", description: "Run JavaScript expression and return result as string", usage: "js <expr>" },
  eval: { category: "Inspection", description: "Run JavaScript from file and return result as string (path must be under /tmp or cwd)", usage: "eval <file>" },
  css: { category: "Inspection", description: "Computed CSS value", usage: "css <sel> <prop>" },
  attrs: { category: "Inspection", description: "Element attributes as JSON", usage: "attrs <sel|@ref>" },
  is: { category: "Inspection", description: "State check (visible/hidden/enabled/disabled/checked/editable/focused)", usage: "is <prop> <sel>" },
  console: { category: "Inspection", description: "Console messages (--errors filters to error/warning)", usage: "console [--clear|--errors]" },
  network: { category: "Inspection", description: "Network requests", usage: "network [--clear]" },
  dialog: { category: "Inspection", description: "Dialog messages", usage: "dialog [--clear]" },
  cookies: { category: "Inspection", description: "All cookies as JSON" },
  storage: { category: "Inspection", description: "Read all localStorage + sessionStorage as JSON, or set <key> <value> to write localStorage", usage: "storage [set k v]" },
  perf: { category: "Inspection", description: "Page load timings" },
  click: { category: "Interaction", description: "Click element", usage: "click <sel>" },
  fill: { category: "Interaction", description: "Fill input", usage: "fill <sel> <val>" },
  select: { category: "Interaction", description: "Select dropdown option by value, label, or visible text", usage: "select <sel> <val>" },
  hover: { category: "Interaction", description: "Hover element", usage: "hover <sel>" },
  type: { category: "Interaction", description: "Type into focused element", usage: "type <text>" },
  press: { category: "Interaction", description: "Press key — Enter, Tab, Escape, ArrowUp/Down/Left/Right, Backspace, Delete, Home, End, PageUp, PageDown, or modifiers like Shift+Enter", usage: "press <key>" },
  scroll: { category: "Interaction", description: "Scroll element into view, or scroll to page bottom if no selector", usage: "scroll [sel]" },
  wait: { category: "Interaction", description: "Wait for element, network idle, or page load (timeout: 15s)", usage: "wait <sel|--networkidle|--load>" },
  upload: { category: "Interaction", description: "Upload file(s)", usage: "upload <sel> <file> [file2...]" },
  viewport: { category: "Interaction", description: "Set viewport size", usage: "viewport <WxH>" },
  cookie: { category: "Interaction", description: "Set cookie on current page domain", usage: "cookie <name>=<value>" },
  "cookie-import": { category: "Interaction", description: "Import cookies from JSON file", usage: "cookie-import <json>" },
  "cookie-import-browser": { category: "Interaction", description: "Import cookies from Comet, Chrome, Arc, Brave, or Edge (opens picker, or use --domain for direct import)", usage: "cookie-import-browser [browser] [--domain d]" },
  header: { category: "Interaction", description: "Set custom request header (colon-separated, sensitive values auto-redacted)", usage: "header <name>:<value>" },
  useragent: { category: "Interaction", description: "Set user agent", usage: "useragent <string>" },
  "dialog-accept": { category: "Interaction", description: "Auto-accept next alert/confirm/prompt. Optional text is sent as the prompt response", usage: "dialog-accept [text]" },
  "dialog-dismiss": { category: "Interaction", description: "Auto-dismiss next dialog" },
  screenshot: { category: "Visual", description: "Save screenshot (supports element crop via CSS/@ref, --clip region, --viewport)", usage: "screenshot [--viewport] [--clip x,y,w,h] [selector|@ref] [path]" },
  pdf: { category: "Visual", description: "Save as PDF", usage: "pdf [path]" },
  responsive: { category: "Visual", description: "Screenshots at mobile (375x812), tablet (768x1024), desktop (1280x720). Saves as {prefix}-mobile.png etc.", usage: "responsive [prefix]" },
  diff: { category: "Visual", description: "Text diff between pages", usage: "diff <url1> <url2>" },
  tabs: { category: "Tabs", description: "List open tabs" },
  tab: { category: "Tabs", description: "Switch to tab", usage: "tab <id>" },
  newtab: { category: "Tabs", description: "Open new tab", usage: "newtab [url]" },
  closetab: { category: "Tabs", description: "Close tab", usage: "closetab [id]" },
  status: { category: "Server", description: "Health check" },
  stop: { category: "Server", description: "Shutdown server" },
  restart: { category: "Server", description: "Restart server" },
  snapshot: { category: "Snapshot", description: "Accessibility tree with @e refs for element selection. Flags: -i interactive only, -c compact, -d N depth limit, -s sel scope, -D diff vs previous, -a annotated screenshot, -o path output, -C cursor-interactive @c refs", usage: "snapshot [flags]" },
  chain: { category: "Meta", description: 'Run commands from JSON stdin. Format: [["cmd","arg1",...],...]' },
  handoff: { category: "Server", description: "Open visible Chrome at current page for user takeover", usage: "handoff [message]" },
  resume: { category: "Server", description: "Re-snapshot after user takeover, return control to AI", usage: "resume" }
};
var allCmds = new Set([...READ_COMMANDS, ...WRITE_COMMANDS, ...META_COMMANDS]);
var descKeys = new Set(Object.keys(COMMAND_DESCRIPTIONS));
for (const cmd of allCmds) {
  if (!descKeys.has(cmd))
    throw new Error(`COMMAND_DESCRIPTIONS missing entry for: ${cmd}`);
}
for (const key of descKeys) {
  if (!allCmds.has(key))
    throw new Error(`COMMAND_DESCRIPTIONS has unknown command: ${key}`);
}

// browse/src/meta-commands.ts
init_url_validation();
init_platform();
import * as Diff2 from "diff";
import * as path5 from "path";
var SAFE_DIRECTORIES2 = [TEMP_DIR, process.cwd()];
function validateOutputPath(filePath) {
  const resolved = path5.resolve(filePath);
  const isSafe = SAFE_DIRECTORIES2.some((dir) => isPathWithin(resolved, dir));
  if (!isSafe) {
    throw new Error(`Path must be within: ${SAFE_DIRECTORIES2.join(", ")}`);
  }
}
async function handleMetaCommand(command, args, bm, shutdown) {
  switch (command) {
    case "tabs": {
      const tabs = await bm.getTabListWithTitles();
      return tabs.map((t) => `${t.active ? "→ " : "  "}[${t.id}] ${t.title || "(untitled)"} — ${t.url}`).join(`
`);
    }
    case "tab": {
      const id = parseInt(args[0], 10);
      if (isNaN(id))
        throw new Error("Usage: browse tab <id>");
      bm.switchTab(id);
      return `Switched to tab ${id}`;
    }
    case "newtab": {
      const url = args[0];
      const id = await bm.newTab(url);
      return `Opened tab ${id}${url ? ` → ${url}` : ""}`;
    }
    case "closetab": {
      const id = args[0] ? parseInt(args[0], 10) : undefined;
      await bm.closeTab(id);
      return `Closed tab${id ? ` ${id}` : ""}`;
    }
    case "status": {
      const page = bm.getPage();
      const tabs = bm.getTabCount();
      return [
        `Status: healthy`,
        `URL: ${page.url()}`,
        `Tabs: ${tabs}`,
        `PID: ${process.pid}`
      ].join(`
`);
    }
    case "url": {
      return bm.getCurrentUrl();
    }
    case "stop": {
      await shutdown();
      return "Server stopped";
    }
    case "restart": {
      console.log("[browse] Restart requested. Exiting for CLI to restart.");
      await shutdown();
      return "Restarting...";
    }
    case "screenshot": {
      const page = bm.getPage();
      let outputPath = `${TEMP_DIR}/browse-screenshot.png`;
      let clipRect;
      let targetSelector;
      let viewportOnly = false;
      const remaining = [];
      for (let i = 0;i < args.length; i++) {
        if (args[i] === "--viewport") {
          viewportOnly = true;
        } else if (args[i] === "--clip") {
          const coords = args[++i];
          if (!coords)
            throw new Error("Usage: screenshot --clip x,y,w,h [path]");
          const parts = coords.split(",").map(Number);
          if (parts.length !== 4 || parts.some(isNaN))
            throw new Error("Usage: screenshot --clip x,y,width,height — all must be numbers");
          clipRect = { x: parts[0], y: parts[1], width: parts[2], height: parts[3] };
        } else if (args[i].startsWith("--")) {
          throw new Error(`Unknown screenshot flag: ${args[i]}`);
        } else {
          remaining.push(args[i]);
        }
      }
      for (const arg of remaining) {
        if (arg.startsWith("@e") || arg.startsWith("@c") || arg.startsWith(".") || arg.startsWith("#") || arg.includes("[")) {
          targetSelector = arg;
        } else {
          outputPath = arg;
        }
      }
      validateOutputPath(outputPath);
      if (clipRect && targetSelector) {
        throw new Error("Cannot use --clip with a selector/ref — choose one");
      }
      if (viewportOnly && clipRect) {
        throw new Error("Cannot use --viewport with --clip — choose one");
      }
      if (targetSelector) {
        const resolved = await bm.resolveRef(targetSelector);
        const locator = "locator" in resolved ? resolved.locator : page.locator(resolved.selector);
        await locator.screenshot({ path: outputPath, timeout: 5000 });
        return `Screenshot saved (element): ${outputPath}`;
      }
      if (clipRect) {
        await page.screenshot({ path: outputPath, clip: clipRect });
        return `Screenshot saved (clip ${clipRect.x},${clipRect.y},${clipRect.width},${clipRect.height}): ${outputPath}`;
      }
      await page.screenshot({ path: outputPath, fullPage: !viewportOnly });
      return `Screenshot saved${viewportOnly ? " (viewport)" : ""}: ${outputPath}`;
    }
    case "pdf": {
      const page = bm.getPage();
      const pdfPath = args[0] || `${TEMP_DIR}/browse-page.pdf`;
      validateOutputPath(pdfPath);
      await page.pdf({ path: pdfPath, format: "A4" });
      return `PDF saved: ${pdfPath}`;
    }
    case "responsive": {
      const page = bm.getPage();
      const prefix = args[0] || `${TEMP_DIR}/browse-responsive`;
      validateOutputPath(prefix);
      const viewports = [
        { name: "mobile", width: 375, height: 812 },
        { name: "tablet", width: 768, height: 1024 },
        { name: "desktop", width: 1280, height: 720 }
      ];
      const originalViewport = page.viewportSize();
      const results = [];
      for (const vp of viewports) {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        const path6 = `${prefix}-${vp.name}.png`;
        await page.screenshot({ path: path6, fullPage: true });
        results.push(`${vp.name} (${vp.width}x${vp.height}): ${path6}`);
      }
      if (originalViewport) {
        await page.setViewportSize(originalViewport);
      }
      return results.join(`
`);
    }
    case "chain": {
      const jsonStr = args[0];
      if (!jsonStr)
        throw new Error(`Usage: echo '[["goto","url"],["text"]]' | browse chain`);
      let commands;
      try {
        commands = JSON.parse(jsonStr);
      } catch {
        throw new Error('Invalid JSON. Expected: [["command", "arg1", "arg2"], ...]');
      }
      if (!Array.isArray(commands))
        throw new Error("Expected JSON array of commands");
      const results = [];
      const { handleReadCommand: handleReadCommand2 } = await Promise.resolve().then(() => (init_read_commands(), exports_read_commands));
      const { handleWriteCommand: handleWriteCommand2 } = await Promise.resolve().then(() => (init_write_commands(), exports_write_commands));
      for (const cmd of commands) {
        const [name, ...cmdArgs] = cmd;
        try {
          let result;
          if (WRITE_COMMANDS.has(name))
            result = await handleWriteCommand2(name, cmdArgs, bm);
          else if (READ_COMMANDS.has(name))
            result = await handleReadCommand2(name, cmdArgs, bm);
          else if (META_COMMANDS.has(name))
            result = await handleMetaCommand(name, cmdArgs, bm, shutdown);
          else
            throw new Error(`Unknown command: ${name}`);
          results.push(`[${name}] ${result}`);
        } catch (err) {
          results.push(`[${name}] ERROR: ${err.message}`);
        }
      }
      return results.join(`

`);
    }
    case "diff": {
      const [url1, url2] = args;
      if (!url1 || !url2)
        throw new Error("Usage: browse diff <url1> <url2>");
      const page = bm.getPage();
      validateNavigationUrl(url1);
      await page.goto(url1, { waitUntil: "domcontentloaded", timeout: 15000 });
      const text1 = await getCleanText(page);
      validateNavigationUrl(url2);
      await page.goto(url2, { waitUntil: "domcontentloaded", timeout: 15000 });
      const text2 = await getCleanText(page);
      const changes = Diff2.diffLines(text1, text2);
      const output = [`--- ${url1}`, `+++ ${url2}`, ""];
      for (const part of changes) {
        const prefix = part.added ? "+" : part.removed ? "-" : " ";
        const lines = part.value.split(`
`).filter((l) => l.length > 0);
        for (const line of lines) {
          output.push(`${prefix} ${line}`);
        }
      }
      return output.join(`
`);
    }
    case "snapshot": {
      return await handleSnapshot(args, bm);
    }
    case "handoff": {
      const message = args.join(" ") || "User takeover requested";
      return await bm.handoff(message);
    }
    case "resume": {
      bm.resume();
      const snapshot = await handleSnapshot(["-i"], bm);
      return `RESUMED
${snapshot}`;
    }
    default:
      throw new Error(`Unknown meta command: ${command}`);
  }
}

// browse/src/cookie-picker-routes.ts
init_cookie_import_browser();

// browse/src/cookie-picker-ui.ts
function getCookiePickerHTML(serverPort) {
  const baseUrl = `http://127.0.0.1:${serverPort}`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cookie Import — gstack browse</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #0a0a0a;
    color: #e0e0e0;
    height: 100vh;
    overflow: hidden;
  }

  /* ─── Header ──────────────────────────── */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 24px;
    border-bottom: 1px solid #222;
    background: #0f0f0f;
  }
  .header h1 {
    font-size: 16px;
    font-weight: 600;
    color: #fff;
  }
  .header .port {
    font-size: 12px;
    color: #666;
    font-family: 'SF Mono', 'Fira Code', monospace;
  }

  /* ─── Layout ──────────────────────────── */
  .container {
    display: flex;
    height: calc(100vh - 53px);
  }
  .panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .panel-left {
    border-right: 1px solid #222;
  }
  .panel-header {
    padding: 16px 20px 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #888;
  }

  /* ─── Browser Pills ───────────────────── */
  .browser-pills {
    display: flex;
    gap: 8px;
    padding: 0 20px 12px;
    flex-wrap: wrap;
  }
  .pill {
    padding: 6px 14px;
    border-radius: 20px;
    border: 1px solid #333;
    background: #1a1a1a;
    color: #aaa;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .pill:hover { border-color: #555; color: #ddd; }
  .pill.active {
    border-color: #4ade80;
    background: #0a2a14;
    color: #4ade80;
  }
  .pill .dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #4ade80;
  }

  /* ─── Search ──────────────────────────── */
  .search-wrap {
    padding: 0 20px 12px;
  }
  .search-input {
    width: 100%;
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid #333;
    background: #141414;
    color: #e0e0e0;
    font-size: 13px;
    outline: none;
    transition: border-color 0.15s;
  }
  .search-input::placeholder { color: #555; }
  .search-input:focus { border-color: #555; }

  /* ─── Domain List ─────────────────────── */
  .domain-list {
    flex: 1;
    overflow-y: auto;
    padding: 0 12px;
  }
  .domain-list::-webkit-scrollbar { width: 6px; }
  .domain-list::-webkit-scrollbar-track { background: transparent; }
  .domain-list::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }

  .domain-row {
    display: flex;
    align-items: center;
    padding: 8px 10px;
    border-radius: 6px;
    transition: background 0.1s;
    gap: 8px;
  }
  .domain-row:hover { background: #1a1a1a; }
  .domain-name {
    flex: 1;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 13px;
    color: #ccc;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .domain-count {
    font-size: 12px;
    color: #666;
    font-family: 'SF Mono', 'Fira Code', monospace;
    min-width: 28px;
    text-align: right;
  }
  .btn-add, .btn-trash {
    width: 28px; height: 28px;
    border-radius: 6px;
    border: 1px solid #333;
    background: #1a1a1a;
    color: #888;
    font-size: 16px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
    flex-shrink: 0;
  }
  .btn-add:hover { border-color: #4ade80; color: #4ade80; background: #0a2a14; }
  .btn-trash:hover { border-color: #f87171; color: #f87171; background: #2a0a0a; }
  .btn-add:disabled, .btn-trash:disabled {
    opacity: 0.3;
    cursor: not-allowed;
    pointer-events: none;
  }
  .btn-add.imported {
    border-color: #333;
    color: #4ade80;
    background: transparent;
    cursor: default;
    font-size: 14px;
  }

  /* ─── Footer ──────────────────────────── */
  .panel-footer {
    padding: 12px 20px;
    border-top: 1px solid #222;
    font-size: 12px;
    color: #666;
  }

  /* ─── Imported Panel ──────────────────── */
  .imported-empty {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #444;
    font-size: 13px;
    padding: 20px;
    text-align: center;
  }

  /* ─── Banner ──────────────────────────── */
  .banner {
    padding: 10px 20px;
    font-size: 13px;
    display: none;
    align-items: center;
    gap: 10px;
  }
  .banner.error {
    background: #1a0a0a;
    border-bottom: 1px solid #3a1111;
    color: #f87171;
  }
  .banner.info {
    background: #0a1a2a;
    border-bottom: 1px solid #112233;
    color: #60a5fa;
  }
  .banner .banner-text { flex: 1; }
  .banner .banner-close, .banner .banner-retry {
    background: none;
    border: 1px solid currentColor;
    color: inherit;
    padding: 3px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
  }

  /* ─── Spinner ─────────────────────────── */
  .spinner {
    display: inline-block;
    width: 14px; height: 14px;
    border: 2px solid #333;
    border-top-color: #4ade80;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .loading-row {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px;
    gap: 10px;
    color: #666;
    font-size: 13px;
  }
</style>
</head>
<body>

<div class="header">
  <h1>Cookie Import</h1>
  <span class="port">localhost:${serverPort}</span>
</div>

<div id="banner" class="banner"></div>

<div class="container">
  <!-- Left Panel: Source Browser -->
  <div class="panel panel-left">
    <div class="panel-header">Source Browser</div>
    <div id="browser-pills" class="browser-pills"></div>
    <div class="search-wrap">
      <input type="text" class="search-input" id="search" placeholder="Search domains..." />
    </div>
    <div class="domain-list" id="source-domains">
      <div class="loading-row"><span class="spinner"></span> Detecting browsers...</div>
    </div>
    <div class="panel-footer" id="source-footer"></div>
  </div>

  <!-- Right Panel: Imported -->
  <div class="panel panel-right">
    <div class="panel-header">Imported to Session</div>
    <div class="domain-list" id="imported-domains">
      <div class="imported-empty">No cookies imported yet</div>
    </div>
    <div class="panel-footer" id="imported-footer"></div>
  </div>
</div>

<script>
(function() {
  const BASE = '${baseUrl}';
  let activeBrowser = null;
  let allDomains = [];
  let importedSet = {};  // domain → count
  let inflight = {};     // domain → true (prevents double-click)

  const $pills = document.getElementById('browser-pills');
  const $search = document.getElementById('search');
  const $sourceDomains = document.getElementById('source-domains');
  const $importedDomains = document.getElementById('imported-domains');
  const $sourceFooter = document.getElementById('source-footer');
  const $importedFooter = document.getElementById('imported-footer');
  const $banner = document.getElementById('banner');

  // ─── Banner ────────────────────────────
  function showBanner(msg, type, retryFn) {
    $banner.className = 'banner ' + type;
    $banner.style.display = 'flex';
    let html = '<span class="banner-text">' + escHtml(msg) + '</span>';
    if (retryFn) {
      html += '<button class="banner-retry" id="banner-retry">Retry</button>';
    }
    html += '<button class="banner-close" id="banner-close">×</button>';
    $banner.innerHTML = html;
    document.getElementById('banner-close').onclick = () => { $banner.style.display = 'none'; };
    if (retryFn) {
      document.getElementById('banner-retry').onclick = () => {
        $banner.style.display = 'none';
        retryFn();
      };
    }
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ─── API ────────────────────────────────
  async function api(path, opts) {
    const res = await fetch(BASE + '/cookie-picker' + path, opts);
    const data = await res.json();
    if (!res.ok) {
      const err = new Error(data.error || 'Request failed');
      err.code = data.code;
      err.action = data.action;
      throw err;
    }
    return data;
  }

  // ─── Init ───────────────────────────────
  async function init() {
    try {
      const [browserData, importedData] = await Promise.all([
        api('/browsers'),
        api('/imported'),
      ]);

      // Populate imported state
      for (const entry of importedData.domains) {
        importedSet[entry.domain] = entry.count;
      }
      renderImported();

      // Render browser pills
      const browsers = browserData.browsers;
      if (browsers.length === 0) {
        $sourceDomains.innerHTML = '<div class="imported-empty">No Chromium browsers detected</div>';
        return;
      }

      $pills.innerHTML = '';
      browsers.forEach(b => {
        const pill = document.createElement('button');
        pill.className = 'pill';
        pill.innerHTML = '<span class="dot"></span>' + escHtml(b.name);
        pill.onclick = () => selectBrowser(b.name);
        $pills.appendChild(pill);
      });

      // Auto-select first browser
      selectBrowser(browsers[0].name);
    } catch (err) {
      showBanner(err.message, 'error', init);
      $sourceDomains.innerHTML = '<div class="imported-empty">Failed to load</div>';
    }
  }

  // ─── Select Browser ────────────────────
  async function selectBrowser(name) {
    activeBrowser = name;

    // Update pills
    $pills.querySelectorAll('.pill').forEach(p => {
      p.classList.toggle('active', p.textContent === name);
    });

    $sourceDomains.innerHTML = '<div class="loading-row"><span class="spinner"></span> Loading domains...</div>';
    $sourceFooter.textContent = '';
    $search.value = '';

    try {
      const data = await api('/domains?browser=' + encodeURIComponent(name));
      allDomains = data.domains;
      renderSourceDomains();
    } catch (err) {
      showBanner(err.message, 'error', err.action === 'retry' ? () => selectBrowser(name) : null);
      $sourceDomains.innerHTML = '<div class="imported-empty">Failed to load domains</div>';
    }
  }

  // ─── Render Source Domains ─────────────
  function renderSourceDomains() {
    const query = $search.value.toLowerCase();
    const filtered = query
      ? allDomains.filter(d => d.domain.toLowerCase().includes(query))
      : allDomains;

    if (filtered.length === 0) {
      $sourceDomains.innerHTML = '<div class="imported-empty">' +
        (query ? 'No matching domains' : 'No cookie domains found') + '</div>';
      $sourceFooter.textContent = '';
      return;
    }

    let html = '';
    for (const d of filtered) {
      const isImported = d.domain in importedSet;
      const isInflight = inflight[d.domain];
      html += '<div class="domain-row">';
      html += '<span class="domain-name">' + escHtml(d.domain) + '</span>';
      html += '<span class="domain-count">' + d.count + '</span>';
      if (isInflight) {
        html += '<span class="btn-add" disabled><span class="spinner" style="width:12px;height:12px;border-width:1.5px;"></span></span>';
      } else if (isImported) {
        html += '<span class="btn-add imported">&#10003;</span>';
      } else {
        html += '<button class="btn-add" data-domain="' + escHtml(d.domain) + '" title="Import">+</button>';
      }
      html += '</div>';
    }
    $sourceDomains.innerHTML = html;

    // Total counts
    const totalDomains = allDomains.length;
    const totalCookies = allDomains.reduce((s, d) => s + d.count, 0);
    $sourceFooter.textContent = totalDomains + ' domains · ' + totalCookies.toLocaleString() + ' cookies';

    // Click handlers
    $sourceDomains.querySelectorAll('.btn-add[data-domain]').forEach(btn => {
      btn.addEventListener('click', () => importDomain(btn.dataset.domain));
    });
  }

  // ─── Import Domain ─────────────────────
  async function importDomain(domain) {
    if (inflight[domain] || domain in importedSet) return;
    inflight[domain] = true;
    renderSourceDomains();

    try {
      const data = await api('/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ browser: activeBrowser, domains: [domain] }),
      });

      if (data.domainCounts) {
        for (const [d, count] of Object.entries(data.domainCounts)) {
          importedSet[d] = (importedSet[d] || 0) + count;
        }
      }
      renderImported();
    } catch (err) {
      showBanner('Import failed for ' + domain + ': ' + err.message, 'error',
        err.action === 'retry' ? () => importDomain(domain) : null);
    } finally {
      delete inflight[domain];
      renderSourceDomains();
    }
  }

  // ─── Render Imported ───────────────────
  function renderImported() {
    const entries = Object.entries(importedSet).sort((a, b) => b[1] - a[1]);

    if (entries.length === 0) {
      $importedDomains.innerHTML = '<div class="imported-empty">No cookies imported yet</div>';
      $importedFooter.textContent = '';
      return;
    }

    let html = '';
    for (const [domain, count] of entries) {
      const isInflight = inflight['remove:' + domain];
      html += '<div class="domain-row">';
      html += '<span class="domain-name">' + escHtml(domain) + '</span>';
      html += '<span class="domain-count">' + count + '</span>';
      if (isInflight) {
        html += '<span class="btn-trash" disabled><span class="spinner" style="width:12px;height:12px;border-width:1.5px;border-top-color:#f87171;"></span></span>';
      } else {
        html += '<button class="btn-trash" data-domain="' + escHtml(domain) + '" title="Remove">&#128465;</button>';
      }
      html += '</div>';
    }
    $importedDomains.innerHTML = html;

    const totalCookies = entries.reduce((s, e) => s + e[1], 0);
    $importedFooter.textContent = entries.length + ' domains · ' + totalCookies.toLocaleString() + ' cookies imported';

    // Click handlers
    $importedDomains.querySelectorAll('.btn-trash[data-domain]').forEach(btn => {
      btn.addEventListener('click', () => removeDomain(btn.dataset.domain));
    });
  }

  // ─── Remove Domain ─────────────────────
  async function removeDomain(domain) {
    if (inflight['remove:' + domain]) return;
    inflight['remove:' + domain] = true;
    renderImported();

    try {
      await api('/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domains: [domain] }),
      });
      delete importedSet[domain];
      renderImported();
      renderSourceDomains(); // update checkmarks
    } catch (err) {
      showBanner('Remove failed for ' + domain + ': ' + err.message, 'error',
        err.action === 'retry' ? () => removeDomain(domain) : null);
    } finally {
      delete inflight['remove:' + domain];
      renderImported();
    }
  }

  // ─── Search ────────────────────────────
  $search.addEventListener('input', renderSourceDomains);

  // ─── Start ─────────────────────────────
  init();
})();
</script>
</body>
</html>`;
}

// browse/src/cookie-picker-routes.ts
var importedDomains = new Set;
var importedCounts = new Map;
function corsOrigin(port) {
  return `http://127.0.0.1:${port}`;
}
function jsonResponse(data, opts) {
  return new Response(JSON.stringify(data), {
    status: opts.status ?? 200,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": corsOrigin(opts.port)
    }
  });
}
function errorResponse(message, code, opts) {
  return jsonResponse({ error: message, code, ...opts.action ? { action: opts.action } : {} }, { port: opts.port, status: opts.status ?? 400 });
}
async function handleCookiePickerRoute(url, req, bm) {
  const pathname = url.pathname;
  const port = parseInt(url.port, 10) || 9400;
  if (req.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": corsOrigin(port),
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
      }
    });
  }
  try {
    if (pathname === "/cookie-picker" && req.method === "GET") {
      const html = getCookiePickerHTML(port);
      return new Response(html, {
        status: 200,
        headers: { "Content-Type": "text/html; charset=utf-8" }
      });
    }
    if (pathname === "/cookie-picker/browsers" && req.method === "GET") {
      const browsers = findInstalledBrowsers();
      return jsonResponse({
        browsers: browsers.map((b) => ({
          name: b.name,
          aliases: b.aliases
        }))
      }, { port });
    }
    if (pathname === "/cookie-picker/domains" && req.method === "GET") {
      const browserName = url.searchParams.get("browser");
      if (!browserName) {
        return errorResponse("Missing 'browser' parameter", "missing_param", { port });
      }
      const result = listDomains(browserName);
      return jsonResponse({
        browser: result.browser,
        domains: result.domains
      }, { port });
    }
    if (pathname === "/cookie-picker/import" && req.method === "POST") {
      let body;
      try {
        body = await req.json();
      } catch {
        return errorResponse("Invalid JSON body", "bad_request", { port });
      }
      const { browser, domains } = body;
      if (!browser)
        return errorResponse("Missing 'browser' field", "missing_param", { port });
      if (!domains || !Array.isArray(domains) || domains.length === 0) {
        return errorResponse("Missing or empty 'domains' array", "missing_param", { port });
      }
      const result = await importCookies(browser, domains);
      if (result.cookies.length === 0) {
        return jsonResponse({
          imported: 0,
          failed: result.failed,
          domainCounts: {},
          message: result.failed > 0 ? `All ${result.failed} cookies failed to decrypt` : "No cookies found for the specified domains"
        }, { port });
      }
      const page = bm.getPage();
      await page.context().addCookies(result.cookies);
      for (const domain of Object.keys(result.domainCounts)) {
        importedDomains.add(domain);
        importedCounts.set(domain, (importedCounts.get(domain) || 0) + result.domainCounts[domain]);
      }
      console.log(`[cookie-picker] Imported ${result.count} cookies for ${Object.keys(result.domainCounts).length} domains`);
      return jsonResponse({
        imported: result.count,
        failed: result.failed,
        domainCounts: result.domainCounts
      }, { port });
    }
    if (pathname === "/cookie-picker/remove" && req.method === "POST") {
      let body;
      try {
        body = await req.json();
      } catch {
        return errorResponse("Invalid JSON body", "bad_request", { port });
      }
      const { domains } = body;
      if (!domains || !Array.isArray(domains) || domains.length === 0) {
        return errorResponse("Missing or empty 'domains' array", "missing_param", { port });
      }
      const page = bm.getPage();
      const context = page.context();
      for (const domain of domains) {
        await context.clearCookies({ domain });
        importedDomains.delete(domain);
        importedCounts.delete(domain);
      }
      console.log(`[cookie-picker] Removed cookies for ${domains.length} domains`);
      return jsonResponse({
        removed: domains.length,
        domains
      }, { port });
    }
    if (pathname === "/cookie-picker/imported" && req.method === "GET") {
      const entries = [];
      for (const domain of importedDomains) {
        entries.push({ domain, count: importedCounts.get(domain) || 0 });
      }
      entries.sort((a, b) => b.count - a.count);
      return jsonResponse({
        domains: entries,
        totalDomains: entries.length,
        totalCookies: entries.reduce((sum, e) => sum + e.count, 0)
      }, { port });
    }
    return new Response("Not found", { status: 404 });
  } catch (err) {
    if (err instanceof CookieImportError) {
      return errorResponse(err.message, err.code, { port, status: 400, action: err.action });
    }
    console.error(`[cookie-picker] Error: ${err.message}`);
    return errorResponse(err.message || "Internal error", "internal_error", { port, status: 500 });
  }
}

// browse/src/config.ts
import * as fs4 from "fs";
import * as path6 from "path";
function getGitRoot() {
  try {
    const proc = Bun.spawnSync(["git", "rev-parse", "--show-toplevel"], {
      stdout: "pipe",
      stderr: "pipe",
      timeout: 2000
    });
    if (proc.exitCode !== 0)
      return null;
    return proc.stdout.toString().trim() || null;
  } catch {
    return null;
  }
}
function resolveConfig(env = process.env) {
  let stateFile;
  let stateDir;
  let projectDir;
  if (env.BROWSE_STATE_FILE) {
    stateFile = env.BROWSE_STATE_FILE;
    stateDir = path6.dirname(stateFile);
    projectDir = path6.dirname(stateDir);
  } else {
    projectDir = getGitRoot() || process.cwd();
    stateDir = path6.join(projectDir, ".gstack");
    stateFile = path6.join(stateDir, "browse.json");
  }
  return {
    projectDir,
    stateDir,
    stateFile,
    consoleLog: path6.join(stateDir, "browse-console.log"),
    networkLog: path6.join(stateDir, "browse-network.log"),
    dialogLog: path6.join(stateDir, "browse-dialog.log")
  };
}
function ensureStateDir(config) {
  try {
    fs4.mkdirSync(config.stateDir, { recursive: true });
  } catch (err) {
    if (err.code === "EACCES") {
      throw new Error(`Cannot create state directory ${config.stateDir}: permission denied`);
    }
    if (err.code === "ENOTDIR") {
      throw new Error(`Cannot create state directory ${config.stateDir}: a file exists at that path`);
    }
    throw err;
  }
  const gitignorePath = path6.join(config.projectDir, ".gitignore");
  try {
    const content = fs4.readFileSync(gitignorePath, "utf-8");
    if (!content.match(/^\.gstack\/?$/m)) {
      const separator = content.endsWith(`
`) ? "" : `
`;
      fs4.appendFileSync(gitignorePath, `${separator}.gstack/
`);
    }
  } catch (err) {
    if (err.code !== "ENOENT") {
      const logPath = path6.join(config.stateDir, "browse-server.log");
      try {
        fs4.appendFileSync(logPath, `[${new Date().toISOString()}] Warning: could not update .gitignore at ${gitignorePath}: ${err.message}
`);
      } catch {}
    }
  }
}
function readVersionHash(execPath = process.execPath) {
  try {
    const versionFile = path6.resolve(path6.dirname(execPath), ".version");
    return fs4.readFileSync(versionFile, "utf-8").trim() || null;
  } catch {
    return null;
  }
}

// browse/src/server.ts
init_buffers();
import * as fs5 from "fs";
import * as path7 from "path";
import * as crypto2 from "crypto";
var config = resolveConfig();
ensureStateDir(config);
var AUTH_TOKEN = crypto2.randomUUID();
var BROWSE_PORT = parseInt(process.env.BROWSE_PORT || "0", 10);
var IDLE_TIMEOUT_MS = parseInt(process.env.BROWSE_IDLE_TIMEOUT || "1800000", 10);
function validateAuth(req) {
  const header = req.headers.get("authorization");
  return header === `Bearer ${AUTH_TOKEN}`;
}
function generateHelpText() {
  const groups = new Map;
  for (const [cmd, meta] of Object.entries(COMMAND_DESCRIPTIONS)) {
    const display = meta.usage || cmd;
    const list = groups.get(meta.category) || [];
    list.push(display);
    groups.set(meta.category, list);
  }
  const categoryOrder = [
    "Navigation",
    "Reading",
    "Interaction",
    "Inspection",
    "Visual",
    "Snapshot",
    "Meta",
    "Tabs",
    "Server"
  ];
  const lines = ["gstack browse — headless browser for AI agents", "", "Commands:"];
  for (const cat of categoryOrder) {
    const cmds = groups.get(cat);
    if (!cmds)
      continue;
    lines.push(`  ${(cat + ":").padEnd(15)}${cmds.join(", ")}`);
  }
  lines.push("");
  lines.push("Snapshot flags:");
  const flagPairs = [];
  for (const flag of SNAPSHOT_FLAGS) {
    const label = flag.valueHint ? `${flag.short} ${flag.valueHint}` : flag.short;
    flagPairs.push(`${label}  ${flag.long}`);
  }
  for (let i = 0;i < flagPairs.length; i += 2) {
    const left = flagPairs[i].padEnd(28);
    const right = flagPairs[i + 1] || "";
    lines.push(`  ${left}${right}`);
  }
  return lines.join(`
`);
}
var CONSOLE_LOG_PATH = config.consoleLog;
var NETWORK_LOG_PATH = config.networkLog;
var DIALOG_LOG_PATH = config.dialogLog;
var lastConsoleFlushed = 0;
var lastNetworkFlushed = 0;
var lastDialogFlushed = 0;
var flushInProgress = false;
async function flushBuffers() {
  if (flushInProgress)
    return;
  flushInProgress = true;
  try {
    const newConsoleCount = consoleBuffer.totalAdded - lastConsoleFlushed;
    if (newConsoleCount > 0) {
      const entries = consoleBuffer.last(Math.min(newConsoleCount, consoleBuffer.length));
      const lines = entries.map((e) => `[${new Date(e.timestamp).toISOString()}] [${e.level}] ${e.text}`).join(`
`) + `
`;
      fs5.appendFileSync(CONSOLE_LOG_PATH, lines);
      lastConsoleFlushed = consoleBuffer.totalAdded;
    }
    const newNetworkCount = networkBuffer.totalAdded - lastNetworkFlushed;
    if (newNetworkCount > 0) {
      const entries = networkBuffer.last(Math.min(newNetworkCount, networkBuffer.length));
      const lines = entries.map((e) => `[${new Date(e.timestamp).toISOString()}] ${e.method} ${e.url} → ${e.status || "pending"} (${e.duration || "?"}ms, ${e.size || "?"}B)`).join(`
`) + `
`;
      fs5.appendFileSync(NETWORK_LOG_PATH, lines);
      lastNetworkFlushed = networkBuffer.totalAdded;
    }
    const newDialogCount = dialogBuffer.totalAdded - lastDialogFlushed;
    if (newDialogCount > 0) {
      const entries = dialogBuffer.last(Math.min(newDialogCount, dialogBuffer.length));
      const lines = entries.map((e) => `[${new Date(e.timestamp).toISOString()}] [${e.type}] "${e.message}" → ${e.action}${e.response ? ` "${e.response}"` : ""}`).join(`
`) + `
`;
      fs5.appendFileSync(DIALOG_LOG_PATH, lines);
      lastDialogFlushed = dialogBuffer.totalAdded;
    }
  } catch {} finally {
    flushInProgress = false;
  }
}
var flushInterval = setInterval(flushBuffers, 1000);
var lastActivity = Date.now();
function resetIdleTimer() {
  lastActivity = Date.now();
}
var idleCheckInterval = setInterval(() => {
  if (Date.now() - lastActivity > IDLE_TIMEOUT_MS) {
    console.log(`[browse] Idle for ${IDLE_TIMEOUT_MS / 1000}s, shutting down`);
    shutdown();
  }
}, 60000);
var browserManager = new BrowserManager;
var isShuttingDown = false;
async function findPort() {
  if (BROWSE_PORT) {
    try {
      const testServer = Bun.serve({ port: BROWSE_PORT, fetch: () => new Response("ok") });
      testServer.stop();
      return BROWSE_PORT;
    } catch {
      throw new Error(`[browse] Port ${BROWSE_PORT} (from BROWSE_PORT env) is in use`);
    }
  }
  const MIN_PORT = 1e4;
  const MAX_PORT = 60000;
  const MAX_RETRIES = 5;
  for (let attempt = 0;attempt < MAX_RETRIES; attempt++) {
    const port = MIN_PORT + Math.floor(Math.random() * (MAX_PORT - MIN_PORT));
    try {
      const testServer = Bun.serve({ port, fetch: () => new Response("ok") });
      testServer.stop();
      return port;
    } catch {
      continue;
    }
  }
  throw new Error(`[browse] No available port after ${MAX_RETRIES} attempts in range ${MIN_PORT}-${MAX_PORT}`);
}
function wrapError(err) {
  const msg = err.message || String(err);
  if (err.name === "TimeoutError" || msg.includes("Timeout") || msg.includes("timeout")) {
    if (msg.includes("locator.click") || msg.includes("locator.fill") || msg.includes("locator.hover")) {
      return `Element not found or not interactable within timeout. Check your selector or run 'snapshot' for fresh refs.`;
    }
    if (msg.includes("page.goto") || msg.includes("Navigation")) {
      return `Page navigation timed out. The URL may be unreachable or the page may be loading slowly.`;
    }
    return `Operation timed out: ${msg.split(`
`)[0]}`;
  }
  if (msg.includes("resolved to") && msg.includes("elements")) {
    return `Selector matched multiple elements. Be more specific or use @refs from 'snapshot'.`;
  }
  return msg;
}
async function handleCommand(body) {
  const { command, args = [] } = body;
  if (!command) {
    return new Response(JSON.stringify({ error: 'Missing "command" field' }), {
      status: 400,
      headers: { "Content-Type": "application/json" }
    });
  }
  try {
    let result;
    if (READ_COMMANDS.has(command)) {
      result = await handleReadCommand(command, args, browserManager);
    } else if (WRITE_COMMANDS.has(command)) {
      result = await handleWriteCommand(command, args, browserManager);
    } else if (META_COMMANDS.has(command)) {
      result = await handleMetaCommand(command, args, browserManager, shutdown);
    } else if (command === "help") {
      const helpText = generateHelpText();
      return new Response(helpText, {
        status: 200,
        headers: { "Content-Type": "text/plain" }
      });
    } else {
      return new Response(JSON.stringify({
        error: `Unknown command: ${command}`,
        hint: `Available commands: ${[...READ_COMMANDS, ...WRITE_COMMANDS, ...META_COMMANDS].sort().join(", ")}`
      }), {
        status: 400,
        headers: { "Content-Type": "application/json" }
      });
    }
    browserManager.resetFailures();
    return new Response(result, {
      status: 200,
      headers: { "Content-Type": "text/plain" }
    });
  } catch (err) {
    browserManager.incrementFailures();
    let errorMsg = wrapError(err);
    const hint = browserManager.getFailureHint();
    if (hint)
      errorMsg += `
` + hint;
    return new Response(JSON.stringify({ error: errorMsg }), {
      status: 500,
      headers: { "Content-Type": "application/json" }
    });
  }
}
async function shutdown() {
  if (isShuttingDown)
    return;
  isShuttingDown = true;
  console.log("[browse] Shutting down...");
  clearInterval(flushInterval);
  clearInterval(idleCheckInterval);
  await flushBuffers();
  await browserManager.close();
  try {
    fs5.unlinkSync(config.stateFile);
  } catch {}
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
async function start() {
  try {
    fs5.unlinkSync(CONSOLE_LOG_PATH);
  } catch {}
  try {
    fs5.unlinkSync(NETWORK_LOG_PATH);
  } catch {}
  try {
    fs5.unlinkSync(DIALOG_LOG_PATH);
  } catch {}
  const port = await findPort();
  await browserManager.launch();
  const startTime = Date.now();
  const server = Bun.serve({
    port,
    hostname: "127.0.0.1",
    fetch: async (req) => {
      resetIdleTimer();
      const url = new URL(req.url);
      if (url.pathname.startsWith("/cookie-picker")) {
        return handleCookiePickerRoute(url, req, browserManager);
      }
      if (url.pathname === "/health") {
        const healthy = await browserManager.isHealthy();
        return new Response(JSON.stringify({
          status: healthy ? "healthy" : "unhealthy",
          uptime: Math.floor((Date.now() - startTime) / 1000),
          tabs: browserManager.getTabCount(),
          currentUrl: browserManager.getCurrentUrl()
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (!validateAuth(req)) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (url.pathname === "/command" && req.method === "POST") {
        const body = await req.json();
        return handleCommand(body);
      }
      return new Response("Not found", { status: 404 });
    }
  });
  const state = {
    pid: process.pid,
    port,
    token: AUTH_TOKEN,
    startedAt: new Date().toISOString(),
    serverPath: path7.resolve(__browseNodeSrcDir, "server.ts"),
    binaryVersion: readVersionHash() || undefined
  };
  const tmpFile = config.stateFile + ".tmp";
  fs5.writeFileSync(tmpFile, JSON.stringify(state, null, 2), { mode: 384 });
  fs5.renameSync(tmpFile, config.stateFile);
  browserManager.serverPort = port;
  console.log(`[browse] Server running on http://127.0.0.1:${port} (PID: ${process.pid})`);
  console.log(`[browse] State file: ${config.stateFile}`);
  console.log(`[browse] Idle timeout: ${IDLE_TIMEOUT_MS / 1000}s`);
}
start().catch((err) => {
  console.error(`[browse] Failed to start: ${err.message}`);
  process.exit(1);
});
export {
  networkBuffer,
  dialogBuffer,
  consoleBuffer,
  addNetworkEntry,
  addDialogEntry,
  addConsoleEntry,
  WRITE_COMMANDS,
  READ_COMMANDS,
  META_COMMANDS
};
