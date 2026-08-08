import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { SkillSettingsPage } from "@/components/workspace/settings/skill-settings-page";
import { SkillRequestError } from "@/core/skills/api";

const state = rs.hoisted(() => ({
  role: "admin" as "admin" | "user",
  isPending: false,
  installSkillFile: rs.fn(),
  enableSkill: rs.fn(),
  toastSuccess: rs.fn(),
  toastError: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
}));

rs.mock("sonner", () => ({
  toast: {
    success: state.toastSuccess,
    error: state.toastError,
  },
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: {
      id: "user-1",
      email: "user@example.com",
      system_role: state.role,
    },
  }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "Loading",
        public: "Public",
        custom: "Custom",
      },
      settings: {
        skills: {
          title: "Agent Skills",
          description: "Manage skills",
          createSkill: "Create skill",
          installSkill: "Install skill",
          installingSkill: "Installing...",
          installSuccess: (name: string) =>
            `Skill "${name}" installed successfully`,
          installFailed: "Failed to install skill",
          installAdminRequired:
            "Admin privileges are required to install agent skills.",
          adminRequired: "Admin required",
          emptyTitle: "No skills",
          emptyDescription: "No skills yet",
          emptyButton: "Create your first skill",
        },
      },
    },
  }),
}));

rs.mock("@/core/skills/hooks", () => ({
  useSkills: () => ({
    skills: [
      {
        name: "public-skill",
        description: "Public skill",
        category: "public",
        license: "MIT",
        enabled: true,
        editable: false,
      },
      {
        name: "custom-skill",
        description: "Custom skill",
        category: "custom",
        license: "MIT",
        enabled: true,
        editable: true,
      },
    ],
    isLoading: false,
    error: null,
  }),
  useEnableSkill: () => ({ mutate: state.enableSkill }),
  useInstallSkillFile: () => ({
    mutateAsync: state.installSkillFile,
    isPending: state.isPending,
  }),
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

beforeEach(() => {
  state.role = "admin";
  state.isPending = false;
  state.installSkillFile.mockReset();
  state.enableSkill.mockReset();
  state.toastSuccess.mockReset();
  state.toastError.mockReset();
});

afterEach(() => {
  cleanup();
});

function selectSkillFile(file = new File(["archive"], "demo.skill")) {
  const input = screen.getByLabelText("Install skill");
  if (!(input instanceof HTMLInputElement)) {
    throw new Error("Expected the install control to be a file input");
  }
  fireEvent.change(input, { target: { files: [file] } });
  return input;
}

describe("SkillSettingsPage local skill install", () => {
  it("starts installation as soon as an administrator selects a file", async () => {
    state.installSkillFile.mockResolvedValue({
      success: true,
      skill_name: "demo-skill",
      message: "installed",
    });

    render(<SkillSettingsPage />);
    const file = new File(["archive"], "demo.skill");
    selectSkillFile(file);

    await waitFor(() => {
      expect(state.installSkillFile).toHaveBeenCalledWith(file);
    });
  });

  it("disables the install controls and shows a pending label", () => {
    state.isPending = true;

    render(<SkillSettingsPage />);

    expect(
      screen
        .getByRole("button", { name: "Installing..." })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(
      screen.getByLabelText("Install skill").hasAttribute("disabled"),
    ).toBe(true);
  });

  it("keeps the install button visible but disabled for non-admin users", () => {
    state.role = "user";

    render(<SkillSettingsPage />);

    expect(
      screen
        .getByRole("button", { name: "Install skill" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(
      screen.getByText(
        "Admin privileges are required to install agent skills.",
      ),
    ).toBeTruthy();
  });

  it("shows success, resets the input, and switches to Custom", async () => {
    state.installSkillFile.mockResolvedValue({
      success: true,
      skill_name: "demo-skill",
      message: "installed",
    });

    render(<SkillSettingsPage />);
    const input = selectSkillFile();

    await waitFor(() => {
      expect(state.toastSuccess).toHaveBeenCalledWith(
        'Skill "demo-skill" installed successfully',
      );
      expect(screen.getByText("custom-skill")).toBeTruthy();
      expect(input.value).toBe("");
    });
  });

  it("shows the backend error detail when installation fails", async () => {
    state.installSkillFile.mockRejectedValue(
      new SkillRequestError(400, "Skill security scan failed"),
    );

    render(<SkillSettingsPage />);
    selectSkillFile();

    await waitFor(() => {
      expect(state.toastError).toHaveBeenCalledWith(
        "Skill security scan failed",
      );
    });
  });

  it("uses the localized fallback for network failures", async () => {
    state.installSkillFile.mockRejectedValue(new TypeError("Failed to fetch"));

    render(<SkillSettingsPage />);
    selectSkillFile();

    await waitFor(() => {
      expect(state.toastError).toHaveBeenCalledWith("Failed to install skill");
      expect(
        screen
          .getByRole("button", { name: "Install skill" })
          .hasAttribute("disabled"),
      ).toBe(false);
    });
  });
});
