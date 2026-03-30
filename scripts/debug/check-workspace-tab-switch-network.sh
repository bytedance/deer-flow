#!/usr/bin/env bash

set -euo pipefail

base_url="${1:-http://localhost:2026}"
entry_path="${2:-/workspace/chats/new}"

probe_dir="/tmp/deer-flow-playwright-probe"
script_file="$probe_dir/check-workspace-tab-switch-network.mjs"
result_file="$(mktemp)"

cleanup() {
  rm -f "$result_file" "$script_file"
}
trap cleanup EXIT

mkdir -p "$probe_dir"

if [[ ! -f "$probe_dir/package.json" ]]; then
  (
    cd "$probe_dir"
    npm init -y >/dev/null 2>&1
  )
fi

if [[ ! -d "$probe_dir/node_modules/playwright" ]]; then
  (
    cd "$probe_dir"
    npm install playwright@1.53.0 >/dev/null 2>&1
  )
fi

cat >"$script_file" <<'EOF'
import { writeFileSync } from "node:fs";
import { chromium } from "playwright";

const baseUrl = process.argv[2];
const entryPath = process.argv[3];
const resultFile = process.argv[4];
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const events = [];

const relevantTypes = new Set(["document", "fetch", "xhr", "script"]);

function isRelevant(url, type) {
  return url.startsWith(baseUrl) && relevantTypes.has(type);
}

function statusOf(response) {
  return typeof response.status === "function"
    ? response.status()
    : response.status;
}

page.on("requestfinished", (request) => {
  const response = request.response();
  if (!response) return;
  const url = request.url();
  const type = request.resourceType();
  if (!isRelevant(url, type)) return;
  events.push({
    ok: true,
    method: request.method(),
    type,
    url,
    status: statusOf(response),
  });
});

page.on("requestfailed", (request) => {
  const url = request.url();
  const type = request.resourceType();
  if (!isRelevant(url, type)) return;
  events.push({
    ok: false,
    method: request.method(),
    type,
    url,
  });
});

async function settle(ms = 2200) {
  await page.waitForTimeout(ms);
}

async function clickAndCollect(label, href, expectedPath) {
  const startIndex = events.length;
  await page.locator(`a[href="${href}"]`).first().click();
  await page.waitForURL(`${baseUrl}${expectedPath}`, { timeout: 15000 });
  await settle();
  return {
    label,
    finalUrl: page.url(),
    requests: events.slice(startIndex),
  };
}

await page.goto(`${baseUrl}${entryPath}`, { waitUntil: "domcontentloaded" });
await settle(4000);
events.length = 0;

const transitions = [];
transitions.push(
  await clickAndCollect("new-to-chats", "/workspace/chats", "/workspace/chats"),
);
transitions.push(
  await clickAndCollect(
    "chats-to-agents",
    "/workspace/agents",
    "/workspace/agents",
  ),
);
transitions.push(
  await clickAndCollect(
    "agents-to-new",
    "/workspace/chats/new",
    "/workspace/chats/new",
  ),
);

writeFileSync(resultFile, JSON.stringify({ transitions }, null, 2));
await browser.close();
EOF

(
  cd "$probe_dir"
  node "$script_file" "$base_url" "$entry_path" "$result_file"
)

check_transition() {
  local label="$1"
  local expected_final_url="$2"
  local forbidden_pattern="$3"
  local description="$4"

  local final_url
  final_url="$(
    node -e '
const fs = require("node:fs");
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const label = process.argv[2];
const match = data.transitions.find((entry) => entry.label === label);
if (!match) process.exit(2);
process.stdout.write(match.finalUrl);
' "$result_file" "$label"
  )"

  if [[ "$final_url" != "$expected_final_url" ]]; then
    echo "FAIL: $label ended on an unexpected route."
    echo "Expected: $expected_final_url"
    echo "Actual:   $final_url"
    exit 1
  fi

  local forbidden_requests
  forbidden_requests="$(
    node -e '
const fs = require("node:fs");
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const label = process.argv[2];
const pattern = new RegExp(process.argv[3]);
const match = data.transitions.find((entry) => entry.label === label);
if (!match) process.exit(2);
const forbidden = match.requests.filter((entry) => pattern.test(entry.url));
process.stdout.write(JSON.stringify(forbidden, null, 2));
' "$result_file" "$label" "$forbidden_pattern"
  )"

  if [[ "$forbidden_requests" != "[]" ]]; then
    echo "FAIL: $description"
    echo "Transition: $label"
    echo "Forbidden requests:"
    echo "$forbidden_requests"
    exit 1
  fi
}

check_transition \
  "new-to-chats" \
  "${base_url}/workspace/chats" \
  "/api/langgraph/threads/search" \
  "switching from new chat to chats still refetches threads."

check_transition \
  "chats-to-agents" \
  "${base_url}/workspace/agents" \
  "/api/agents" \
  "switching from chats to agents still refetches the agents list."

check_transition \
  "agents-to-new" \
  "${base_url}/workspace/chats/new" \
  "/api/models" \
  "switching from agents to new chat still refetches models."

echo "PASS: workspace tab switching reuses warmed data for chats, agents, and models."
echo "Entry route: ${base_url}${entry_path}"
