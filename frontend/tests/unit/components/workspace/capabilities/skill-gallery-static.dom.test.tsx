import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "true" },
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "admin", system_role: "admin" } }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
}));
rs.mock("next/dynamic", () => ({ default: () => () => null }));
rs.mock("@/core/skills/hooks", () => ({
  useSkills: () => ({
    skills: [
      {
        name: "custom-demo",
        description: "Custom",
        category: "custom",
        license: "",
        enabled: true,
        editable: true,
      },
      {
        name: "public-demo",
        description: "Public",
        category: "public",
        license: "",
        enabled: true,
        editable: false,
      },
    ],
    isLoading: false,
    error: null,
  }),
  useEnableSkill: () => ({ mutate: rs.fn(), isPending: false }),
  useUploadSkillArchive: () => ({
    mutateAsync: rs.fn(),
    isPending: false,
  }),
  useSkillManagement: () => ({
    canManage: false,
    sourceInstallAvailable: false,
  }),
}));
rs.mock("@/components/workspace/capabilities/skill-diagnostics", () => ({
  SkillDiagnostics: () => <div data-testid="skill-diagnostics" />,
}));
rs.mock("@/components/workspace/capabilities/custom-skill-details", () => ({
  CustomSkillDetails: () => <div data-testid="custom-skill-details" />,
}));

import { SkillGallery } from "@/components/workspace/capabilities/skill-gallery";
import { enUS } from "@/core/i18n/locales/en-US";

afterEach(cleanup);

describe("static skill gallery", () => {
  it("hides all custom management and install entries in static mode", () => {
    render(<SkillGallery />);

    expect(screen.queryByRole("button", { name: "Install skill" })).toBeNull();
    expect(screen.queryByTestId("skill-diagnostics")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Community" }));
    expect(screen.queryByRole("button", { name: "Install skill" })).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "My skills" }));
    expect(screen.queryByRole("switch", { name: /custom-demo/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /^View details custom-demo$/ }),
    ).toBeNull();
    expect(screen.queryByTestId("custom-skill-details")).toBeNull();
  });
});
