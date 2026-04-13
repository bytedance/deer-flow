import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const desktopRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(desktopRoot, "..");
const bundleRoot = path.join(desktopRoot, "bundle-resources", "app-bundle");
const bundledNodeDir = path.join(bundleRoot, "node-runtime");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    cwd: repoRoot,
    env: { ...process.env, ...options.env },
  });

  if (result.status !== 0) {
    throw new Error(`Command failed: ${command} ${args.join(" ")}`);
  }
}

function copyIntoBundle(source, destination) {
  cpSync(source, destination, {
    recursive: true,
    force: true,
    dereference: false,
  });
}

rmSync(bundleRoot, { recursive: true, force: true });
mkdirSync(bundleRoot, { recursive: true });
mkdirSync(bundledNodeDir, { recursive: true });

if (!existsSync(path.join(repoRoot, "backend", ".venv"))) {
  throw new Error("backend/.venv is required for the packaged desktop runtime");
}

const bundledGatewayPort = "8002";

run("pnpm", ["--dir", "frontend", "build"], {
  env: {
    BETTER_AUTH_SECRET: "deerflow-desktop-bundled-secret",
    DEER_FLOW_DESKTOP_BUNDLE: "1",
    DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: `http://127.0.0.1:${bundledGatewayPort}`,
    DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL: `http://127.0.0.1:${bundledGatewayPort}/api`,
    NEXT_PUBLIC_BACKEND_BASE_URL: "",
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: "/api/langgraph",
    NODE_ENV: "production",
  },
});

copyIntoBundle(path.join(repoRoot, "frontend", ".next", "standalone"), bundleRoot);
copyIntoBundle(
  path.join(repoRoot, "frontend", ".next", "static"),
  path.join(bundleRoot, ".next", "static"),
);
copyIntoBundle(path.join(repoRoot, "frontend", "public"), path.join(bundleRoot, "public"));
copyIntoBundle(path.join(repoRoot, "backend"), path.join(bundleRoot, "backend"));
copyIntoBundle(path.join(repoRoot, "skills"), path.join(bundleRoot, "skills"));
copyIntoBundle(
  path.join(repoRoot, "config.example.yaml"),
  path.join(bundleRoot, "config.example.yaml"),
);
copyIntoBundle(
  process.execPath,
  path.join(bundledNodeDir, process.platform === "win32" ? "node.exe" : "node"),
);

if (existsSync(path.join(repoRoot, "extensions_config.json"))) {
  copyIntoBundle(
    path.join(repoRoot, "extensions_config.json"),
    path.join(bundleRoot, "extensions_config.json"),
  );
} else {
  copyIntoBundle(
    path.join(repoRoot, "extensions_config.example.json"),
    path.join(bundleRoot, "extensions_config.json"),
  );
}
