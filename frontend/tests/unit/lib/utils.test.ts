import { expect, test } from "vitest";

import { prettyAgentName } from "@/lib/utils";

test("prettyAgentName expands canonical acronyms", () => {
  expect(prettyAgentName("cfi-dashboard-msi-vpn")).toBe(
    "CFI Dashboard MSI VPN",
  );
});

test("prettyAgentName leaves normal words title-cased", () => {
  expect(prettyAgentName("fleet-ops-analyst")).toBe("Fleet Ops Analyst");
});

