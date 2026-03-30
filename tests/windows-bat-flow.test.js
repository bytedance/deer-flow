import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const repoRoot = process.cwd();

const startBat = fs.readFileSync(path.join(repoRoot, "start-windows.bat"), "utf8");
const startPs1 = fs.readFileSync(path.join(repoRoot, "scripts", "start-windows.ps1"), "utf8");

assert.doesNotMatch(startBat, /backup-custom\.bat/i, "upstream start-windows.bat must not depend on personal backup flow");
assert.doesNotMatch(startBat, /git fetch origin main/i, "upstream start-windows.bat must not perform repo sync logic");
assert.doesNotMatch(startBat, /git merge origin\/main/i, "upstream start-windows.bat must not merge upstream branches");
assert.match(startBat, /scripts\\start-windows\.ps1/i, "upstream start-windows.bat should invoke scripts/start-windows.ps1");
assert.match(startBat, /pause/i, "upstream start-windows.bat should pause on failure");

assert.match(startPs1, /\$ports = @\(2024, 8001, 2026\)/, "start-windows.ps1 should preflight 2026 instead of 3000");
assert.match(startPs1, /pnpm run dev -- --port 2026/i, "start-windows.ps1 should start Next dev on port 2026");
assert.match(startPs1, /Wait-PortTcp -Port 2026/i, "start-windows.ps1 should wait for frontend port 2026");
assert.match(startPs1, /Opening browser: http:\/\/localhost:2026/i, "start-windows.ps1 should open the browser on 2026");

console.log("OK");
