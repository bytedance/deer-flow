import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  inspect: rs.fn(),
  install: rs.fn(),
  enable: rs.fn(),
  remove: rs.fn(),
  invalidate: rs.fn(),
}));
rs.mock("@/core/skills/api", () => ({
  ...rs.requireActual("@/core/skills/api"),
  inspectSkillSource: mocks.inspect,
  installSkillSource: mocks.install,
  deleteCustomSkill: mocks.remove,
}));
rs.mock("@/core/skills/hooks", () => ({
  useEnableSkill: () => ({ mutateAsync: mocks.enable, isPending: false }),
}));
rs.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidate }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

import { SkillSourceInstallDialog } from "@/components/workspace/capabilities/skill-source-install-dialog";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  SkillRequestError,
  type InstallSkillResponse,
  type SkillSourcePreview,
} from "@/core/skills/api";

const text = enUS.settings.skills;
const preview: SkillSourcePreview = {
  source: "owner/repo@demo",
  source_url: "https://skills.sh/owner/repo/demo",
  skill_name: "demo",
  description: "A <strong>plain-text</strong> description",
  snapshot_digest: "a".repeat(64),
  upstream_hash: null,
  file_count: 2,
  total_bytes: 128,
};

function renderDialog(onClose = rs.fn(), onInstalled = rs.fn()) {
  render(
    <SkillSourceInstallDialog onClose={onClose} onInstalled={onInstalled} />,
  );
  fireEvent.change(screen.getByLabelText(text.sourceLabel), {
    target: { value: preview.source },
  });
  return { onClose, onInstalled };
}

async function openPreview(onClose = rs.fn(), onInstalled = rs.fn()) {
  mocks.inspect.mockResolvedValue(preview);
  const callbacks = renderDialog(onClose, onInstalled);
  fireEvent.click(screen.getByRole("button", { name: text.sourceInspect }));
  await screen.findByText(preview.skill_name);
  return callbacks;
}

beforeEach(() => {
  mocks.inspect.mockReset();
  mocks.install.mockReset();
  mocks.enable.mockReset().mockResolvedValue(undefined);
  mocks.remove.mockReset().mockResolvedValue({ success: true });
  mocks.invalidate.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

describe("source skill installation", () => {
  it("trims surrounding whitespace before inspecting a source", async () => {
    mocks.inspect.mockResolvedValue(preview);
    renderDialog();
    fireEvent.change(screen.getByLabelText(text.sourceLabel), {
      target: { value: `  ${preview.source}  ` },
    });
    fireEvent.click(screen.getByRole("button", { name: text.sourceInspect }));

    await screen.findByText(preview.skill_name);
    expect(mocks.inspect).toHaveBeenCalledWith(
      preview.source,
      expect.any(AbortSignal),
    );
  });

  it("walks input, preview, install, and immediate lifecycle actions", async () => {
    mocks.install.mockResolvedValue({
      success: true,
      skill_name: "demo",
      message: "Installed",
      enabled: true,
    });
    const { onInstalled } = await openPreview();

    expect(screen.getByText(preview.description)).toBeTruthy();
    expect(document.querySelector("strong")).toBeNull();
    expect(screen.getByText(text.sourceFinalScanNotice)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: text.sourceInstall }));

    await screen.findByText(text.sourceSuccessTitle);
    expect(mocks.install).toHaveBeenCalledWith(
      {
        source: preview.source,
        expected_snapshot_digest: preview.snapshot_digest,
      },
      expect.any(AbortSignal),
    );
    expect(onInstalled).toHaveBeenCalledTimes(1);
    expect(screen.getByText(text.sourceSuccessDescription)).toBeTruthy();
    expect(screen.getByText(text.sourceVisibilityNotice)).toBeTruthy();

    const enabled = screen.getByRole("switch", {
      name: `${text.sourceEnabled} demo`,
    });
    fireEvent.click(enabled);
    expect(mocks.enable).toHaveBeenCalledWith({
      skillName: "demo",
      enabled: false,
    });
    fireEvent.click(screen.getByRole("button", { name: text.deleteSkill }));
    fireEvent.click(screen.getByRole("button", { name: text.confirmDelete }));
    expect(mocks.remove).toHaveBeenCalledWith("demo");
  });

  it("shows the persisted disabled state after reinstalling", async () => {
    mocks.install.mockResolvedValue({
      success: true,
      skill_name: "demo",
      message: "Installed",
      enabled: false,
    });
    await openPreview();
    fireEvent.click(screen.getByRole("button", { name: text.sourceInstall }));

    await screen.findByText(text.sourceSuccessDisabledDescription);
    expect(screen.queryByText(text.sourceSuccessDescription)).toBeNull();
    expect(
      screen
        .getByRole("switch", { name: `${text.sourceEnabled} demo` })
        .getAttribute("aria-checked"),
    ).toBe("false");
  });

  it.each([
    ["skill_source_invalid", text.sourceInvalid],
    ["skill_source_not_configured", text.sourceNotConfigured],
    ["skill_source_auth_failed", text.sourceAuthFailed],
    ["skill_source_unavailable", text.sourceUnavailable],
    ["skill_source_rate_limited", text.sourceRateLimited("12")],
    ["skill_source_not_found", text.sourceNotFound],
    ["skill_source_snapshot_unusable", text.sourceSnapshotUnusable],
    ["skill_source_changed", text.sourceChanged],
  ])(
    "renders the %s branch without matching server messages",
    async (code, expected) => {
      mocks.inspect.mockRejectedValue(
        new SkillRequestError(400, "untrusted server detail", {
          code,
          retryAfter: code === "skill_source_rate_limited" ? "12" : null,
        }),
      );
      renderDialog();
      fireEvent.click(screen.getByRole("button", { name: text.sourceInspect }));

      await screen.findByText(expected);
      expect(screen.getByText("untrusted server detail")).toBeTruthy();
    },
  );

  it("discards a stale preview after skill_source_changed", async () => {
    mocks.install.mockRejectedValue(
      new SkillRequestError(409, "changed", { code: "skill_source_changed" }),
    );
    await openPreview();
    fireEvent.click(screen.getByRole("button", { name: text.sourceInstall }));
    await screen.findByText(text.sourceChanged);

    fireEvent.click(screen.getByRole("button", { name: text.sourceRetry }));
    expect(screen.getByLabelText(text.sourceLabel)).toHaveProperty(
      "value",
      preview.source,
    );
    expect(screen.queryByText(preview.snapshot_digest)).toBeNull();
  });

  it("shows final scan findings returned by install", async () => {
    mocks.install.mockRejectedValue(
      new SkillRequestError(400, "Blocked by policy", {
        code: "skill_security_scan_failed",
        findings: [
          {
            rule_id: "shell",
            severity: "HIGH",
            file: "SKILL.md",
            line: 4,
            message: "Shell execution",
            remediation: "Remove it",
          },
        ],
      }),
    );
    await openPreview();
    fireEvent.click(screen.getByRole("button", { name: text.sourceInstall }));

    await screen.findByText(text.skillSecurityScanFailed);
    expect(screen.getByText(/HIGH shell/)).toBeTruthy();
  });

  it("refreshes on close because aborting does not cancel a drained install", async () => {
    const onClose = rs.fn();
    mocks.inspect.mockImplementation(
      (_source: string, signal?: AbortSignal) => {
        // ES2022 target: Promise.withResolvers is not in the configured libs.
        let rejectPromise: (reason?: unknown) => void = () => undefined;
        const promise = new Promise<SkillSourcePreview>((_resolve, reject) => {
          rejectPromise = reject;
        });
        signal?.addEventListener("abort", () =>
          rejectPromise(new DOMException("Aborted", "AbortError")),
        );
        return promise;
      },
    );
    renderDialog(onClose);
    fireEvent.click(screen.getByRole("button", { name: text.sourceInspect }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(mocks.invalidate).toHaveBeenCalledWith({ queryKey: ["skills"] });
  });

  it("refreshes again when an install dismissed in flight settles", async () => {
    const onClose = rs.fn();
    let installSignal: AbortSignal | undefined;
    let finishInstall: (result: InstallSkillResponse) => void = () => undefined;
    mocks.install.mockImplementation((_request, signal?: AbortSignal) => {
      installSignal = signal;
      // ES2022 target: Promise.withResolvers is not in the configured libs.
      return new Promise<InstallSkillResponse>((resolve) => {
        finishInstall = resolve;
      });
    });
    await openPreview(onClose);
    fireEvent.click(screen.getByRole("button", { name: text.sourceInstall }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(installSignal?.aborted).toBe(false);
    expect(mocks.invalidate).toHaveBeenCalledTimes(1);

    await act(async () => {
      finishInstall({
        success: true,
        skill_name: "demo",
        message: "Installed",
        enabled: true,
      });
      await Promise.resolve();
    });
    expect(mocks.invalidate).toHaveBeenCalledTimes(2);
  });
});
