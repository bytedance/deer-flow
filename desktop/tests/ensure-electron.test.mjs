import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import test from "node:test";

const { getElectronInstallStatus, getElectronRepairCommand } = await import(
  "../scripts/ensure-electron.mjs"
);

void test("reports reinstall required when electron package exists but binary is missing", async () => {
  const tempDir = await mkdtemp(path.join(os.tmpdir(), "deer-electron-test-"));

  try {
    const electronDir = path.join(tempDir, "node_modules", "electron");
    await mkdir(path.join(electronDir, "dist"), { recursive: true });
    await writeFile(path.join(electronDir, "dist", "version"), "37.2.0");
    await writeFile(
      path.join(electronDir, "path.txt"),
      "Electron.app/Contents/MacOS/Electron",
    );

    const status = await getElectronInstallStatus({ desktopDir: tempDir });

    assert.equal(status.needsInstall, true);
    assert.equal(status.reason, "binary-missing");
    assert.match(status.expectedBinaryPath, /Electron\.app\/Contents\/MacOS\/Electron$/);
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
});

void test("uses Electron's install script when package exists but binary is missing", () => {
  const command = getElectronRepairCommand({ reason: "binary-missing" });

  assert.deepEqual(command, {
    cmd: process.execPath,
    args: ["node_modules/electron/install.js"],
  });
});
